#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RIEMANN_TRIPWIRE_DRILL_V3.py
============================

Mejoras propuestas (implementación directa):

1) Drill dirigido por déficit:
   - Lee blocks desde JSONL (block_summary) y elige el peor bloque (max deficit).
   - Ejecuta un escaneo ultra-alta resolución SOLO en ese bloque.

2) Split-on-demand (subdivisión recursiva) para capturar ceros muy cercanos:
   - Si un intervalo [a,b] tiene bracket (Z(a)*Z(b) <= 0), refinamos 1 cero.
   - Luego (y esto es la mejora clave), si el intervalo es "grande" vs spacing local,
     subdividimos recursivamente para detectar ceros múltiples dentro del mismo intervalo.

3) Criterio de salida por cobertura:
   - Usa N(T) (Riemann–von Mangoldt) para estimar ceros esperados en el bloque.
   - Detiene si deficit <= tol_deficit o si ya no aparecen nuevos ceros tras una pasada.

Requisitos:
  pip install mpmath

Uso:
  # Drill automático al peor bloque leyendo un JSONL previo:
  python RIEMANN_TRIPWIRE_DRILL_V3.py --jsonl zeros_tripwire.jsonl --t0 14 --t1 1014 --alpha 0.15

  # Drill manual a un bloque específico:
  python RIEMANN_TRIPWIRE_DRILL_V3.py --block_start 14 --block_end 114 --alpha_drill 0.03 --out drill.jsonl

Notas:
- Este script es compatible con el enfoque anterior (Hardy Z + tripwire).
- No depende de solvers internos; usa bracket + bisection/secant robusto.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable

import mpmath as mp


# --------------------------
# Hardy Z
# --------------------------

def hardy_Z(t: mp.mpf) -> mp.mpf:
    return mp.re(mp.exp(1j * mp.siegeltheta(t)) * mp.zeta(mp.mpf("0.5") + 1j * t))


# --------------------------
# Teoría: spacing y conteo esperado
# --------------------------

TWO_PI = 2.0 * math.pi

def delta_spacing(T: float) -> float:
    x = T / TWO_PI
    if x <= 1.0:
        return 1.0
    denom = math.log(x)
    if denom <= 0.0 or not math.isfinite(denom):
        return 1.0
    return TWO_PI / denom

def N_riemann_von_mangoldt(T: float) -> float:
    if T <= 0.0:
        return 0.0
    x = T / TWO_PI
    if x <= 0.0:
        return 0.0
    return x * math.log(x) - x + 0.875


# --------------------------
# Root finder: bracket + bisection/secant
# --------------------------

@dataclass
class RootResult:
    root: mp.mpf
    iters: int
    converged: bool
    f_at_root: mp.mpf

def refine_root_bracket(
    f: Callable[[mp.mpf], mp.mpf],
    a: mp.mpf,
    b: mp.mpf,
    fa: mp.mpf,
    fb: mp.mpf,
    tol: mp.mpf,
    max_iter: int = 80
) -> RootResult:
    if fa == 0:
        return RootResult(a, 0, True, fa)
    if fb == 0:
        return RootResult(b, 0, True, fb)

    left, right = a, b
    fleft, fright = fa, fb

    x0, f0 = left, fleft
    x1, f1 = right, fright

    for it in range(1, max_iter + 1):
        mid = (left + right) / 2
        fmid = f(mid)

        if mp.fabs(fmid) <= tol:
            return RootResult(mid, it, True, fmid)
        if mp.fabs(right - left) <= tol:
            return RootResult(mid, it, True, fmid)

        use_secant = False
        xs = None
        if f1 != f0:
            xs = x1 - f1 * (x1 - x0) / (f1 - f0)
            if xs is not None and (left < xs < right):
                use_secant = True

        if use_secant:
            fs = f(xs)
            if fleft * fs <= 0:
                right, fright = xs, fs
            else:
                left, fleft = xs, fs
            x0, f0 = left, fleft
            x1, f1 = right, fright
            continue

        if fleft * fmid <= 0:
            right, fright = mid, fmid
        else:
            left, fleft = mid, fmid

        x0, f0 = left, fleft
        x1, f1 = right, fright

    mid = (left + right) / 2
    fmid = f(mid)
    return RootResult(mid, max_iter, False, fmid)


# --------------------------
# Dedupe
# --------------------------

def dedupe_insert_sorted(roots: List[float], t: float, eps: float) -> bool:
    if not roots:
        roots.append(t)
        return True
    lo, hi = 0, len(roots) - 1
    while lo <= hi:
        m = (lo + hi) // 2
        if roots[m] < t:
            lo = m + 1
        else:
            hi = m - 1
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
# Split-on-demand drill
# --------------------------

@dataclass
class DrillConfig:
    alpha: float = 0.03                  # paso base: h = alpha * Delta(T)
    min_step: float = 0.003              # piso de paso (para no ir a cero)
    max_step: float = 0.12               # techo de paso (no queremos intervalos enormes)
    split_ratio: float = 0.35            # si h > split_ratio * Delta(T) y hubo bracket, considerar split
    max_split_depth: int = 8             # profundidad recursiva
    dps: int = 80
    tol_exp: int = 18                    # tol = 1e-18
    max_iter_root: int = 90
    dedupe_eps: float = 1e-8
    tol_deficit: float = 1.0             # parar drill si deficit <= 1.0 (en ese bloque)

def step_at(t: float, cfg: DrillConfig) -> float:
    h = cfg.alpha * delta_spacing(max(t, 10.0))
    h = max(cfg.min_step, min(cfg.max_step, h))
    return h

def should_split_interval(a: float, b: float, cfg: DrillConfig) -> bool:
    midT = 0.5 * (a + b)
    Delta = delta_spacing(max(midT, 10.0))
    h = (b - a)
    return h > (cfg.split_ratio * Delta)

def drill_interval_recursive(
    f: Callable[[mp.mpf], mp.mpf],
    a: float,
    b: float,
    fa: mp.mpf,
    fb: mp.mpf,
    cfg: DrillConfig,
    roots: List[float],
    fp,
    depth: int = 0
) -> int:
    """
    Retorna cuántos ceros NUEVOS insertó (dedupe).
    Requiere fa*fb <= 0 para entrar.
    Hace:
      - Refina un cero en [a,b]
      - Si el intervalo es grande vs spacing local, subdivide y busca ceros adicionales
    """
    if depth > cfg.max_split_depth:
        return 0

    tol = mp.mpf(10) ** (-cfg.tol_exp)

    rr = refine_root_bracket(
        f,
        mp.mpf(a), mp.mpf(b),
        fa, fb,
        tol=tol,
        max_iter=cfg.max_iter_root
    )

    t_root = float(rr.root)
    ok = rr.converged and (abs(float(rr.f_at_root)) <= float(mp.mpf(10) * tol))
    inserted = False
    new_count = 0

    if ok:
        inserted = dedupe_insert_sorted(roots, t_root, cfg.dedupe_eps)
        new_count += int(inserted)

    jlog(fp, "drill_zero_candidate", {
        "a": a, "b": b,
        "depth": depth,
        "root": t_root,
        "converged": rr.converged,
        "iters": rr.iters,
        "abs_f": float(mp.fabs(rr.f_at_root)),
        "accepted": bool(ok and inserted),
        "split_check": bool(should_split_interval(a, b, cfg))
    })

    # Split-on-demand: si el intervalo es grande, explorar subintervalos para ceros adicionales
    if not should_split_interval(a, b, cfg):
        return new_count

    # Divide en dos y revisa brackets en cada mitad
    m = 0.5 * (a + b)
    fm = f(mp.mpf(m))

    # left half
    if fa == 0 or fm == 0 or (fa * fm) <= 0:
        new_count += drill_interval_recursive(f, a, m, fa, fm, cfg, roots, fp, depth + 1)

    # right half
    if fm == 0 or fb == 0 or (fm * fb) <= 0:
        new_count += drill_interval_recursive(f, m, b, fm, fb, cfg, roots, fp, depth + 1)

    return new_count

def drill_block(
    block_start: float,
    block_end: float,
    cfg: DrillConfig,
    out_path: str
) -> List[float]:
    mp.mp.dps = cfg.dps
    roots: List[float] = []

    expected = N_riemann_von_mangoldt(block_end) - N_riemann_von_mangoldt(block_start)

    with open(out_path, "a", encoding="utf-8") as fp:
        jlog(fp, "drill_start", {
            "block_start": block_start,
            "block_end": block_end,
            "expected": float(expected),
            "cfg": cfg.__dict__,
        })

        prev_found = -1
        passes = 0

        # Repetimos pasadas hasta estabilizar o cumplir deficit
        while True:
            passes += 1
            found_before = len(roots)

            t = block_start
            z_prev = hardy_Z(mp.mpf(t))

            while t < block_end:
                h = step_at(t, cfg)
                t_next = min(block_end, t + h)
                z_next = hardy_Z(mp.mpf(t_next))

                if z_prev == 0 or z_next == 0 or (z_prev * z_next) <= 0:
                    _ = drill_interval_recursive(
                        hardy_Z,
                        t, t_next,
                        z_prev, z_next,
                        cfg,
                        roots,
                        fp,
                        depth=0
                    )

                t = t_next
                z_prev = z_next

            found_after = len(roots)
            deficit = float(expected) - float(found_after)

            jlog(fp, "drill_pass_summary", {
                "pass": passes,
                "found_total": int(found_after),
                "expected": float(expected),
                "deficit": float(deficit),
                "new_this_pass": int(found_after - found_before),
            })

            # Criterios de salida:
            # 1) deficit <= tol_deficit
            if deficit <= cfg.tol_deficit:
                break
            # 2) no se encontraron nuevos ceros en esta pasada
            if found_after == found_before:
                break
            # 3) guardrail por estabilidad
            if prev_found == found_after:
                break
            prev_found = found_after

        jlog(fp, "drill_end", {
            "found_total": int(len(roots)),
            "expected": float(expected),
            "final_deficit": float(float(expected) - float(len(roots))),
            "passes": passes,
        })

    return roots


# --------------------------
# Selección automática del peor bloque desde JSONL previo
# --------------------------

def find_worst_block_from_jsonl(jsonl_path: str, default_block: float = 100.0) -> Optional[Tuple[float, float, float]]:
    """
    Busca eventos 'block_summary' y retorna (start, end, deficit) con mayor deficit.
    Si no hay, retorna None.
    """
    worst = None
    worst_def = -1e18

    with open(jsonl_path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "block_summary":
                continue
            bs = rec.get("block_start")
            be = rec.get("block_end")
            df = rec.get("deficit")
            if bs is None or be is None or df is None:
                continue
            try:
                dfv = float(df)
                bsv = float(bs)
                bev = float(be)
            except Exception:
                continue
            if dfv > worst_def:
                worst_def = dfv
                worst = (bsv, bev, dfv)

    return worst


# --------------------------
# CLI
# --------------------------

def main():
    ap = argparse.ArgumentParser(description="Riemann Drill v3: deficit-directed split-on-demand mining")
    ap.add_argument("--jsonl", type=str, default="", help="JSONL previo con block_summary (para elegir peor bloque)")
    ap.add_argument("--block_start", type=float, default=0.0, help="inicio bloque (manual)")
    ap.add_argument("--block_end", type=float, default=0.0, help="fin bloque (manual)")
    ap.add_argument("--alpha_drill", type=float, default=0.03, help="alpha para drill")
    ap.add_argument("--dps", type=int, default=80)
    ap.add_argument("--tol_exp", type=int, default=18)
    ap.add_argument("--split_ratio", type=float, default=0.35)
    ap.add_argument("--max_split_depth", type=int, default=8)
    ap.add_argument("--min_step", type=float, default=0.003)
    ap.add_argument("--max_step", type=float, default=0.12)
    ap.add_argument("--tol_deficit", type=float, default=1.0)
    ap.add_argument("--out", type=str, default="drill.jsonl")
    args = ap.parse_args()

    # Decide bloque objetivo
    target = None
    if args.jsonl:
        target = find_worst_block_from_jsonl(args.jsonl)
        if target is None:
            raise SystemExit("No se encontraron block_summary en el JSONL provisto.")
        block_start, block_end, deficit = target
    else:
        if args.block_start == 0.0 and args.block_end == 0.0:
            raise SystemExit("Provee --jsonl o bien --block_start/--block_end.")
        block_start, block_end, deficit = args.block_start, args.block_end, float("nan")

    cfg = DrillConfig(
        alpha=float(args.alpha_drill),
        min_step=float(args.min_step),
        max_step=float(args.max_step),
        split_ratio=float(args.split_ratio),
        max_split_depth=int(args.max_split_depth),
        dps=int(args.dps),
        tol_exp=int(args.tol_exp),
        tol_deficit=float(args.tol_deficit),
    )

    roots = drill_block(block_start, block_end, cfg, args.out)

    print("DRILL TARGET")
    print(f"block: [{block_start}, {block_end}]  worst_deficit(prev)={deficit}")
    print(f"found: {len(roots)}")
    if roots:
        print(f"first: {roots[0]:.12f}")
        print(f"last : {roots[-1]:.12f}")


if __name__ == "__main__":
    main()
