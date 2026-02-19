#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
riemann_pipeline_utils.py
=========================
Capas de robustez para minería de ceros:

A) DEDUPE por cero (clustering por proximidad en t)
B) Edge-handling: etiqueta candidatos cerca de bordes de bloque
C) Clasificación estricta: CONFIRMED vs VALLEY_ONLY
D) Confirmación determinista: bracket + Brent (si hay cambio de signo en Z real)
E) Repetibilidad barata: re-scan con offset step/2 (helper)

No asume tu implementación de Hardy–Siegel/Z(t):
- Tú inyectas funciones: Z(t), o HardyZ(t), etc.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import math


# ---------------------------
# A) Dedupe / Clustering
# ---------------------------

def cluster_by_t(ts: List[float], eps: float) -> List[List[float]]:
    ts = sorted(ts)
    clusters: List[List[float]] = []
    cur: List[float] = []
    for t in ts:
        if not cur or abs(t - cur[-1]) <= eps:
            cur.append(t)
        else:
            clusters.append(cur)
            cur = [t]
    if cur:
        clusters.append(cur)
    return clusters


def dedupe_candidates(
    candidates: List[Dict[str, Any]],
    key_t: str = "t_center",
    eps: float = 0.075,
    prefer: str = "min_absZ",  # "min_absZ" or "max_conf"
) -> List[Dict[str, Any]]:
    """
    Agrupa candidatos por cercanía en t y conserva 1 representante por cluster.
    """
    # extrae t
    items = []
    for c in candidates:
        t = c.get(key_t, c.get("t", None))
        if t is None:
            continue
        try:
            t = float(t)
        except Exception:
            continue
        items.append((t, c))

    if not items:
        return []

    items.sort(key=lambda x: x[0])
    out: List[Dict[str, Any]] = []

    cur: List[Tuple[float, Dict[str, Any]]] = []
    for t, c in items:
        if not cur or abs(t - cur[-1][0]) <= eps:
            cur.append((t, c))
        else:
            out.append(_pick_rep(cur, prefer=prefer))
            cur = [(t, c)]
    if cur:
        out.append(_pick_rep(cur, prefer=prefer))
    return out


def _pick_rep(cluster: List[Tuple[float, Dict[str, Any]]], prefer: str) -> Dict[str, Any]:
    if prefer == "max_conf":
        def conf(c): 
            try: return float(c.get("confidence", 0.0))
            except Exception: return 0.0
        return max((c for _, c in cluster), key=conf)
    # default: min_absZ
    def absz(c):
        z = c.get("absZ", c.get("abs_z", c.get("absZ_val", None)))
        if z is None:
            return float("inf")
        try:
            return abs(float(z))
        except Exception:
            return float("inf")
    return min((c for _, c in cluster), key=absz)


# ---------------------------
# B) Edge tagging
# ---------------------------

def tag_edges(
    candidates: List[Dict[str, Any]],
    T1: float,
    T2: float,
    step: float,
    key_t: str = "t_center",
    edge_steps: float = 2.0,
) -> None:
    """
    Marca edge=True si candidato está a < edge_steps*step del borde.
    """
    margin = edge_steps * step
    for c in candidates:
        t = c.get(key_t, c.get("t", None))
        if t is None:
            c["edge"] = False
            continue
        try:
            t = float(t)
        except Exception:
            c["edge"] = False
            continue
        c["edge"] = (t - T1) < margin or (T2 - t) < margin


# ---------------------------
# C) Clasificación estricta
# ---------------------------

def classify_candidate(c: Dict[str, Any]) -> str:
    """
    Regla dura:
    - CONFIRMED si status ya lo dice o si tiene bracket+root_converged
    - VALLEY_ONLY en otro caso
    """
    st = str(c.get("status", "")).upper()
    if st in ("CONFIRMED", "ZERO_CONFIRMED", "BRACKETED"):
        return "CONFIRMED"
    if c.get("bracket") and c.get("root_converged") is True:
        return "CONFIRMED"
    return "VALLEY_ONLY"


# ---------------------------
# D) Brent root finding
# ---------------------------

@dataclass
class BrentResult:
    converged: bool
    root: Optional[float]
    iters: int
    f_root: Optional[float]


def brent_root(
    f: Callable[[float], float],
    a: float,
    b: float,
    tol: float = 1e-12,
    max_iter: int = 100
) -> BrentResult:
    """
    Implementación compacta de Brent (robusta) sin dependencias externas.
    Requiere f(a)*f(b) <= 0.
    """
    fa = f(a); fb = f(b)
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return BrentResult(False, None, 0, None)
    if fa == 0.0:
        return BrentResult(True, a, 0, 0.0)
    if fb == 0.0:
        return BrentResult(True, b, 0, 0.0)
    if fa * fb > 0:
        return BrentResult(False, None, 0, None)

    c, fc = a, fa
    d = e = b - a

    for it in range(1, max_iter + 1):
        if fb * fc > 0:
            c, fc = a, fa
            d = e = b - a

        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb

        tol1 = 2.0 * 1e-16 * abs(b) + 0.5 * tol
        m = 0.5 * (c - b)

        if abs(m) <= tol1 or fb == 0.0:
            return BrentResult(True, b, it, fb)

        if abs(e) >= tol1 and abs(fa) > abs(fb):
            s = fb / fa
            if a == c:
                p = 2 * m * s
                q = 1 - s
            else:
                q = fa / fc
                r = fb / fc
                p = s * (2 * m * q * (q - r) - (b - a) * (r - 1))
                q = (q - 1) * (r - 1) * (s - 1)

            if p > 0:
                q = -q
            p = abs(p)

            cond1 = 2 * p < min(3 * m * q - abs(tol1 * q), abs(e * q))
            if cond1:
                e = d
                d = p / q
            else:
                d = m
                e = m
        else:
            d = m
            e = m

        a, fa = b, fb
        b = b + (d if abs(d) > tol1 else (tol1 if m > 0 else -tol1))
        fb = f(b)

    return BrentResult(False, b, max_iter, fb)


def try_bracket_and_confirm(
    z_real: Callable[[float], float],
    t0: float,
    step: float,
    expand_steps: int = 6,
    tol: float = 1e-12
) -> Dict[str, Any]:
    """
    Dado un valle (t0), intenta:
    1) encontrar bracket [a,b] con cambio de signo en z_real
    2) aplicar Brent para raíz

    Devuelve dict con bracket/root/root_converged/status.
    """
    # busca bracket expandiendo simétricamente
    a = t0
    fa = z_real(a)
    if not math.isfinite(fa):
        return {"status": "VALLEY_ONLY", "root_converged": False}

    for k in range(1, expand_steps + 1):
        left = t0 - k * step
        right = t0 + k * step
        fl = z_real(left)
        fr = z_real(right)
        if math.isfinite(fl) and fa * fl <= 0:
            br = (left, a)
            res = brent_root(z_real, br[0], br[1], tol=tol)
            return _pack_confirm(br, res)
        if math.isfinite(fr) and fa * fr <= 0:
            br = (a, right)
            res = brent_root(z_real, br[0], br[1], tol=tol)
            return _pack_confirm(br, res)

    return {"status": "VALLEY_ONLY", "root_converged": False}


def _pack_confirm(br: Tuple[float, float], res: BrentResult) -> Dict[str, Any]:
    out = {"bracket": [float(br[0]), float(br[1])], "root_converged": bool(res.converged)}
    if res.converged and res.root is not None:
        out.update({"status": "CONFIRMED", "t_root": float(res.root), "f_root": float(res.f_root or 0.0), "brent_iters": int(res.iters)})
    else:
        out.update({"status": "VALLEY_ONLY"})
    return out


# ---------------------------
# E) Repetibilidad barata
# ---------------------------

# ---------------------------
# F) Riemann-von Mangoldt & Density
# ---------------------------

def n_riemann_von_mangoldt(t: float) -> float:
    """Theoretical cumulative number of zeros up to t."""
    if t < 10: return 0
    return (t / (2 * math.pi)) * (math.log(t / (2 * math.pi)) - 1) + 7/8

def get_mean_spacing(t: float) -> float:
    """Theoretical mean spacing Delta(T) at height T."""
    if t < 2*math.pi: return 1.0
    return (2 * math.pi) / math.log(t / (2 * math.pi))
