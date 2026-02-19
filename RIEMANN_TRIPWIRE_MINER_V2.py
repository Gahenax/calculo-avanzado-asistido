#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RIEMANN_TRIPWIRE_MINER_V2.py
============================

Minería de ceros de Riemann (Hardy Z) usando:
1) Detección por cambio de signo (tripwire): Z(t_i)*Z(t_{i+1}) <= 0
2) Refinamiento robusto por bisección + secante (headshot)
3) Paso adaptativo basado en densidad teórica: h(T)=alpha*Delta(T)
4) Auditoría por conteo esperado N(T) (Riemann-von Mangoldt)
5) Logging JSONL por eventos (cero encontrado, bloque, salud)

Requisitos:
  pip install mpmath

Ejemplo:
  python RIEMANN_TRIPWIRE_MINER_V2.py --t0 14 --t1 1014 --alpha 0.15 --block 100 --dps 50 --out zeros.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import mpmath as mp


# --------------------------
# Hardy Z (real en la línea crítica)
# --------------------------

def hardy_Z(t: mp.mpf) -> mp.mpf:
    # Z(t) = exp(i*theta(t)) * zeta(1/2 + i t), valor real para t real
    # mpmath: mp.zeta, mp.siegeltheta
    return mp.re(mp.exp(1j * mp.siegeltheta(t)) * mp.zeta(mp.mpf('0.5') + 1j * t))


# --------------------------
# Teoría: spacing y conteo esperado
# --------------------------

TWO_PI = 2.0 * math.pi

def delta_spacing(T: float) -> float:
    # Delta(T) ~ 2π / log(T/2π)
    x = T / TWO_PI
    if x <= 1.0:
        return 1.0
    denom = math.log(x)
    if denom <= 0.0 or not math.isfinite(denom):
        return 1.0
    return TWO_PI / denom

def N_riemann_von_mangoldt(T: float) -> float:
    # N(T) ~ (T/2π) log(T/2π) - (T/2π) + 7/8
    if T <= 0.0:
        return 0.0
    x = T / TWO_PI
    if x <= 0.0:
        return 0.0
    return x * math.log(x) - x + 0.875


# --------------------------
# Root finder: bisección + secante (robusto con bracket)
# --------------------------

@dataclass
class RootResult:
    root: mp.mpf
    iters: int
    converged: bool
    f_at_root: mp.mpf

def refine_root_bracket(
    f,
    a: mp.mpf,
    b: mp.mpf,
    fa: mp.mpf,
    fb: mp.mpf,
    tol: mp.mpf,
    max_iter: int = 80
) -> RootResult:
    """
    Requiere bracket: fa*fb <= 0.
    Mezcla bisección (garantía) + secante (aceleración).
    """
    if fa == 0:
        return RootResult(a, 0, True, fa)
    if fb == 0:
        return RootResult(b, 0, True, fb)

    left, right = a, b
    fleft, fright = fa, fb

    # Inicializa secante
    x0, f0 = left, fleft
    x1, f1 = right, fright

    for it in range(1, max_iter + 1):
        mid = (left + right) / 2
        fmid = f(mid)

        # Criterios de parada
        if mp.fabs(fmid) <= tol:
            return RootResult(mid, it, True, fmid)
        if mp.fabs(right - left) <= tol:
            return RootResult(mid, it, True, fmid)

        # Intento secante (si es estable)
        use_secant = False
        xs = None
        if f1 != f0:
            xs = x1 - f1 * (x1 - x0) / (f1 - f0)
            # Asegura que caiga dentro del bracket
            if xs is not None and (left < xs < right):
                use_secant = True

        if use_secant:
            fs = f(xs)
            # Actualiza bracket
            if fleft * fs <= 0:
                right, fright = xs, fs
            else:
                left, fleft = xs, fs
            # Actualiza puntos para próxima secante
            x0, f0 = left, fleft
            x1, f1 = right, fright
            continue

        # Fallback bisección segura
        if fleft * fmid <= 0:
            right, fright = mid, fmid
        else:
            left, fleft = mid, fmid

        x0, f0 = left, fleft
        x1, f1 = right, fright

    # No convergió en iteraciones, devuelve mejor mid
    mid = (left + right) / 2
    fmid = f(mid)
    return RootResult(mid, max_iter, False, fmid)


# --------------------------
# Dedupe
# --------------------------

def dedupe_append(roots: List[float], t: float, eps: float) -> bool:
    """
    Inserta si no existe uno ya muy cerca.
    roots debe estar ordenada.
    """
    if not roots:
        roots.append(t)
        return True
    # búsqueda binaria simple
    lo, hi = 0, len(roots) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if roots[mid] < t:
            lo = mid + 1
        else:
            hi = mid - 1
    # lo es posición de inserción
    if lo > 0 and abs(roots[lo - 1] - t) <= eps:
        return False
    if lo < len(roots) and abs(roots[lo] - t) <= eps:
        return False
    roots.insert(lo, t)
    return True


# --------------------------
# JSONL logger
# --------------------------

def jlog(fp, event: str, payload: Dict):
    rec = {"ts": time.time(), "event": event, **payload}
    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fp.flush()


# --------------------------
# Miner
# --------------------------

def mine_zeros(
    t0: float,
    t1: float,
    alpha: float,
    block: float,
    dps: int,
    tol_exp: int,
    max_iter_root: int,
    out_path: str,
    dedupe_eps: float,
    min_step: float,
    max_step: float
):
    mp.mp.dps = dps
    tol = mp.mpf(10) ** (-tol_exp)

    roots: List[float] = []

    with open(out_path, "a", encoding="utf-8") as fp:
        jlog(fp, "run_start", {
            "t0": t0, "t1": t1, "alpha": alpha, "block": block,
            "dps": dps, "tol_exp": tol_exp,
            "dedupe_eps": dedupe_eps,
            "min_step": min_step, "max_step": max_step,
        })

        # Iteración por bloques para auditoría
        bstart = t0
        while bstart < t1:
            bend = min(t1, bstart + block)

            expected = N_riemann_von_mangoldt(bend) - N_riemann_von_mangoldt(bstart)
            found_before = len(roots)

            # Escaneo dentro del bloque
            t = bstart
            t_mp = mp.mpf(t)
            z_prev = hardy_Z(t_mp)

            # Asegura paso inicial
            while t < bend:
                # paso adaptativo por densidad
                h = alpha * delta_spacing(max(t, 10.0))
                h = max(min_step, min(max_step, h))
                t_next = min(bend, t + h)

                t_next_mp = mp.mpf(t_next)
                z_next = hardy_Z(t_next_mp)

                # Tripwire: bracket por cambio de signo (incluye cero exacto)
                if z_prev == 0 or z_next == 0 or (z_prev * z_next) <= 0:
                    a = mp.mpf(t)
                    b = mp.mpf(t_next)
                    fa = z_prev
                    fb = z_next

                    rr = refine_root_bracket(
                        hardy_Z, a, b, fa, fb,
                        tol=tol, max_iter=max_iter_root
                    )

                    t_root = float(rr.root)
                    ok = rr.converged and (abs(float(rr.f_at_root)) <= float(mp.mpf(10) * tol))
                    inserted = False
                    if ok:
                        inserted = dedupe_append(roots, t_root, dedupe_eps)

                    jlog(fp, "zero_candidate", {
                        "a": float(a), "b": float(b),
                        "root": t_root,
                        "converged": rr.converged,
                        "iters": rr.iters,
                        "abs_f": float(mp.fabs(rr.f_at_root)),
                        "accepted": bool(ok and inserted),
                    })

                # avanza
                t = t_next
                z_prev = z_next

            found_after = len(roots)
            found_block = found_after - found_before
            deficit = float(expected) - float(found_block)

            # Señales de salud (simple y brutal)
            health = {
                "block_start": bstart,
                "block_end": bend,
                "expected": float(expected),
                "found": int(found_block),
                "deficit": float(deficit),
                "total_found": int(found_after),
            }
            jlog(fp, "block_summary", health)

            bstart = bend

        jlog(fp, "run_end", {"total_found": len(roots)})

    return roots


# --------------------------
# CLI
# --------------------------

def main():
    ap = argparse.ArgumentParser(description="Riemann Tripwire Miner v2 (sign-change bracketing + robust refine)")
    ap.add_argument("--t0", type=float, default=14.0)
    ap.add_argument("--t1", type=float, default=1014.0)
    ap.add_argument("--alpha", type=float, default=0.15, help="h(T)=alpha*Delta(T)")
    ap.add_argument("--block", type=float, default=100.0, help="auditoría por bloques")
    ap.add_argument("--dps", type=int, default=50, help="precisión mpmath")
    ap.add_argument("--tol_exp", type=int, default=15, help="tolerancia = 10^-tol_exp")
    ap.add_argument("--max_iter_root", type=int, default=80)
    ap.add_argument("--out", type=str, default="zeros_tripwire.jsonl")
    ap.add_argument("--dedupe_eps", type=float, default=1e-7, help="dedupe en t")
    ap.add_argument("--min_step", type=float, default=0.01)
    ap.add_argument("--max_step", type=float, default=0.25)
    args = ap.parse_args()

    roots = mine_zeros(
        t0=args.t0,
        t1=args.t1,
        alpha=args.alpha,
        block=args.block,
        dps=args.dps,
        tol_exp=args.tol_exp,
        max_iter_root=args.max_iter_root,
        out_path=args.out,
        dedupe_eps=args.dedupe_eps,
        min_step=args.min_step,
        max_step=args.max_step
    )

    print(f"TOTAL ROOTS FOUND: {len(roots)}")
    if roots:
        print(f"FIRST: {roots[0]:.12f}")
        print(f"LAST : {roots[-1]:.12f}")


if __name__ == "__main__":
    main()
