#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AG_RIEMANN_RESCUE_LAB.py
=======================

Laboratorio integrado (Antigravity-ready) para:
- Minería de ceros en la línea crítica via Hardy Z(t) (mpmath)
- Pipeline Explore/Focus/Verify con bins de déficit y alpha adaptativo
- Dedupe dinámico por gap local
- Auditorías: r-mean (ratio statistic) y fuerza de Dyson (equilibrio / drift)
- Exporta reporte JSON reproducible

Requisitos:
  pip install mpmath numpy matplotlib

Ejemplo de uso:
  python3 AG_RIEMANN_RESCUE_LAB.py \
    --T0 1314 --T1 1414 \
    --alpha_explore 0.12 \
    --bin_width 0.5 \
    --deficit_threshold 0.10 \
    --focus_rounds 2 \
    --out_json rescue_1314.json

Notas:
- Este script trabaja con ceros de Z(t) (Hardy), es decir, ceros en Re(s)=1/2.
- El "déficit" usa N_asym(T) (aprox. asintótica) solo como guía para dirigir el drill.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

try:
    import mpmath as mp
except ImportError as e:
    raise SystemExit("mpmath no está instalado. Ejecuta: pip install mpmath") from e


# -----------------------------------------------------------------------------
# 0) Conteo esperado (guía) y normalización
# -----------------------------------------------------------------------------

def N_asym(T: float) -> float:
    """
    N(T) ≈ (T/2π) log(T/2π) - (T/2π) + 7/8
    Guía para dirigir bins deficitarios (no prueba formal).
    """
    if T <= 0:
        return 0.0
    x = T / (2.0 * math.pi)
    return x * math.log(max(1e-12, x)) - x + 7.0 / 8.0


def expected_in_interval(a: float, b: float) -> float:
    return max(0.0, N_asym(b) - N_asym(a))


def normalize_t(t: np.ndarray) -> np.ndarray:
    """
    Normalización por densidad local: t -> t * log(t)/(2π)
    """
    t = np.asarray(t, dtype=float)
    if np.any(t <= 0):
        raise ValueError("Todos los t deben ser > 0")
    return t * np.log(t) / (2.0 * math.pi)


# -----------------------------------------------------------------------------
# 1) Dedupe dinámico por gap local
# -----------------------------------------------------------------------------

@dataclass
class DedupePolicy:
    tol_abs_max: float = 1e-10
    tol_gap_frac: float = 0.05


def dedupe_sorted(zeros_sorted: List[float], policy: DedupePolicy) -> List[float]:
    if not zeros_sorted:
        return []
    z = np.array(zeros_sorted, dtype=float)
    z.sort()

    out = [float(z[0])]
    for i in range(1, len(z)):
        prev = out[-1]
        curr = float(z[i])

        gap_left = curr - prev
        gap_right = float(z[i + 1] - curr) if (i + 1) < len(z) else gap_left
        local_gap = max(1e-16, min(gap_left, gap_right))

        tol_i = min(policy.tol_abs_max, policy.tol_gap_frac * local_gap)
        if abs(curr - prev) > tol_i:
            out.append(curr)

    return out


# -----------------------------------------------------------------------------
# 2) Auditorías: r-statistics y fuerza Dyson local
# -----------------------------------------------------------------------------

def r_stats(zeros_sorted: np.ndarray) -> Dict[str, float]:
    z = np.asarray(zeros_sorted, dtype=float)
    z.sort()
    gaps = np.diff(z)
    if gaps.size < 2:
        return {"n": float(max(0, gaps.size)), "r_mean": float("nan")}
    r = np.minimum(gaps[:-1], gaps[1:]) / np.maximum(gaps[:-1], gaps[1:])
    return {
        "n": float(r.size),
        "r_mean": float(np.mean(r)),
        "r_median": float(np.median(r)),
        "r_p05": float(np.percentile(r, 5)),
        "r_p95": float(np.percentile(r, 95)),
    }


def local_dyson_force(t: np.ndarray, K: int = 20) -> np.ndarray:
    t = np.asarray(t, dtype=float)
    if t.ndim != 1 or t.size < (2 * K + 1):
        # Fallback for small datasets
        K = max(1, (t.size - 1) // 2)
    
    x = np.sort(normalize_t(t))
    N = x.size
    F = np.full(N, np.nan, dtype=float)
    for i in range(K, N - K):
        xi = x[i]
        s = 0.0
        for m in range(1, K + 1):
            s += 1.0 / (xi - x[i - m])
            s += 1.0 / (xi - x[i + m])
        F[i] = s
    return F


def get_stats(arr: np.ndarray) -> Dict[str, float]:
    a = arr[np.isfinite(arr)]
    if a.size == 0:
        return {"n": 0.0}
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    idx = np.arange(a.size, dtype=float)
    
    drift_slope = 0.0
    drift_intercept = 0.0
    if a.size >= 2:
        A = np.vstack([idx, np.ones_like(idx)]).T
        drift_slope, drift_intercept = np.linalg.lstsq(A, a, rcond=None)[0]
        
    return {
        "n": float(a.size),
        "mean": float(np.mean(a)),
        "median": med,
        "std": float(np.std(a, ddof=1)) if a.size > 1 else 0.0,
        "mad": mad,
        "drift_slope": float(drift_slope),
        "drift_intercept": float(drift_intercept),
        "p05": float(np.percentile(a, 5)),
        "p95": float(np.percentile(a, 95)),
    }


# -----------------------------------------------------------------------------
# 3) Déficit por bins y política alpha adaptativa
# -----------------------------------------------------------------------------

@dataclass
class BinDeficit:
    a: float
    b: float
    expected: float
    found: int
    deficit: float


def bin_deficits(zeros_sorted: np.ndarray, T0: float, T1: float, bin_width: float) -> List[BinDeficit]:
    z = np.asarray(zeros_sorted, dtype=float)
    z.sort()
    bins = np.arange(T0, T1 + 1e-12, bin_width)

    out: List[BinDeficit] = []
    j = 0
    for i in range(len(bins) - 1):
        a, b = float(bins[i]), float(bins[i + 1])
        start = j
        while j < z.size and z[j] < b:
            j += 1
        found = int(np.sum((z[start:j] >= a) & (z[start:j] < b)))
        exp = expected_in_interval(a, b)
        out.append(BinDeficit(a=a, b=b, expected=exp, found=found, deficit=max(0.0, exp - found)))
    return out


@dataclass
class AlphaPolicy:
    alpha_base: float = 0.02
    alpha_lupa: float = 0.004
    alpha_super: float = 0.001


def choose_alpha_for_region(zeros_in_region: np.ndarray, policy: AlphaPolicy) -> float:
    z = np.asarray(zeros_in_region, dtype=float)
    z.sort()
    if z.size < 6:
        return policy.alpha_lupa

    gaps = np.diff(z)
    if gaps.size == 0:
        return policy.alpha_lupa

    q10 = float(np.percentile(gaps, 10))
    q02 = float(np.percentile(gaps, 2))

    if q10 <= 0:
        return policy.alpha_super
    if q02 < q10 * 0.5:
        return policy.alpha_super
    return policy.alpha_lupa


# -----------------------------------------------------------------------------
# 4) Backend real mpmath: Hardy Z + scan + refinamiento robusto
# -----------------------------------------------------------------------------

@dataclass
class EngineConfig:
    dps_base: int = 50
    dps_focus: int = 80
    max_cache: int = 20000
    z_abs_floor: mp.mpf = mp.mpf("1e-40")
    refine_iters: int = 240
    refine_tol: mp.mpf = mp.mpf("1e-30")
    known_tol: float = 1e-10


class ZEngine:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._cache: Dict[float, mp.mpf] = {}

    def _cache_get(self, t: float) -> Optional[mp.mpf]:
        return self._cache.get(t)

    def _cache_put(self, t: float, val: mp.mpf) -> None:
        if len(self._cache) >= self.cfg.max_cache:
            # Simple eviction
            keys = list(self._cache.keys())
            for i in range(len(keys) // 4):
                self._cache.pop(keys[i])
        self._cache[t] = val

    def hardyZ(self, t: float, dps: Optional[int] = None) -> mp.mpf:
        cached = self._cache_get(t)
        if cached is not None:
            return cached

        use_dps = self.cfg.dps_base if dps is None else dps
        with mp.workdps(use_dps):
            tt = mp.mpf(t)
            theta = mp.siegeltheta(tt)
            z = mp.zeta(mp.mpf("0.5") + 1j * tt)
            Z = mp.re(mp.exp(1j * theta) * z)
            if mp.fabs(Z) < self.cfg.z_abs_floor:
                Z = mp.mpf("0.0")

        self._cache_put(t, Z)
        # Use mp.mpf explicitly to ensure type stability
        return mp.mpf(Z)

    @staticmethod
    def _sign(x: mp.mpf) -> int:
        if x == 0:
            return 0
        return 1 if x > 0 else -1

    def refine_root_bisect(self, a: float, b: float, dps: int) -> Optional[float]:
        with mp.workdps(dps):
            Za = self.hardyZ(a, dps=dps)
            Zb = self.hardyZ(b, dps=dps)
            sa, sb = self._sign(Za), self._sign(Zb)

            if sa == 0:
                return float(a)
            if sb == 0:
                return float(b)
            if sa * sb > 0:
                return None

            lo, hi = mp.mpf(a), mp.mpf(b)
            Zlo = Za

            for _ in range(self.cfg.refine_iters):
                if (hi - lo) <= self.cfg.refine_tol:
                    return float((lo + hi) / 2)

                mid = (lo + hi) / 2
                tm = float(mid)
                Zm = self.hardyZ(tm, dps=dps)
                sm = self._sign(Zm)

                if sm == 0:
                    return float(mid)

                if self._sign(Zlo) * sm < 0:
                    hi = mid
                else:
                    lo = mid
                    Zlo = Zm

            return float((lo + hi) / 2)

    def fast_scan(self, T0: float, T1: float, alpha: float) -> List[float]:
        zeros: List[float] = []
        t = float(T0)
        if t >= T1:
            return zeros

        prev = self.hardyZ(t, dps=self.cfg.dps_base)
        prev_s = self._sign(prev)

        while t < T1:
            t2 = min(T1, t + alpha)
            cur = self.hardyZ(t2, dps=self.cfg.dps_base)
            cur_s = self._sign(cur)

            if prev_s == 0:
                zeros.append(float(t))
            elif cur_s == 0:
                zeros.append(float(t2))
            elif prev_s * cur_s < 0:
                r = self.refine_root_bisect(t, t2, dps=self.cfg.dps_base)
                if r is not None:
                    zeros.append(float(r))

            t, prev, prev_s = t2, cur, cur_s

        return zeros

    def drill_focus(self, a: float, b: float, alpha: float, known_zeros: List[float]) -> List[float]:
        kz = sorted(float(x) for x in known_zeros)
        tol = self.cfg.known_tol

        def is_known(x: float) -> bool:
            i = bisect.bisect_left(kz, x)
            if i < len(kz) and abs(kz[i] - x) <= tol:
                return True
            if i > 0 and abs(kz[i - 1] - x) <= tol:
                return True
            return False

        zeros: List[float] = []
        t = float(a)
        if t >= b:
            return zeros

        prev = self.hardyZ(t, dps=self.cfg.dps_base)
        prev_s = self._sign(prev)

        while t < b:
            t2 = min(b, t + alpha)
            cur = self.hardyZ(t2, dps=self.cfg.dps_base)
            cur_s = self._sign(cur)

            cand: Optional[float] = None
            if prev_s == 0:
                cand = float(t)
            elif cur_s == 0:
                cand = float(t2)
            elif prev_s * cur_s < 0:
                cand = self.refine_root_bisect(t, t2, dps=self.cfg.dps_focus)

            if cand is not None and (not is_known(cand)):
                zeros.append(cand)

            t, prev, prev_s = t2, cur, cur_s

        return zeros


# -----------------------------------------------------------------------------
# 5) Pipeline: Explore/Focus/Verify
# -----------------------------------------------------------------------------

FastScanFn = Callable[[float, float, float], List[float]]
DrillFn = Callable[[float, float, float, List[float]], List[float]]


@dataclass
class Hooks:
    fast_scan: FastScanFn
    drill_focus: DrillFn


from dataclasses import dataclass, field

@dataclass
class RunConfig:
    T0: float
    T1: float
    alpha_explore: float = 0.20  # Fast-track exploration
    bin_width: float = 1.0       # Wider bins for faster density checks
    deficit_threshold: float = 0.15 # Relaxed threshold
    max_focus_rounds: int = 2
    dyson_K: int = 15            # Faster Dyson check
    dedupe: DedupePolicy = field(default_factory=DedupePolicy)
    alpha_policy: AlphaPolicy = field(default_factory=AlphaPolicy)


def run_pipeline(cfg: RunConfig, hooks: Hooks) -> Dict:
    # Pass A: Explore
    zeros = hooks.fast_scan(cfg.T0, cfg.T1, cfg.alpha_explore)
    zeros = dedupe_sorted(zeros, cfg.dedupe)

    # Pass B: Focus (dirigido)
    for _ in range(cfg.max_focus_rounds):
        z_arr = np.array(zeros, dtype=float)
        z_arr.sort()

        deficits = bin_deficits(z_arr, cfg.T0, cfg.T1, cfg.bin_width)
        hot = [bd for bd in deficits if bd.deficit >= cfg.deficit_threshold]

        new_total = 0
        for bd in hot:
            in_bin = z_arr[(z_arr >= bd.a) & (z_arr < bd.b)]
            alpha = choose_alpha_for_region(in_bin, cfg.alpha_policy)
            new_zeros = hooks.drill_focus(bd.a, bd.b, alpha, zeros)
            if new_zeros:
                zeros.extend(new_zeros)
                zeros = dedupe_sorted(zeros, cfg.dedupe)
                new_total += len(new_zeros)

        if new_total == 0:
            break

    zeros_arr = np.array(zeros, dtype=float)
    zeros_arr.sort()

    expected_total = expected_in_interval(cfg.T0, cfg.T1)
    found_total = int(((zeros_arr >= cfg.T0) & (zeros_arr <= cfg.T1)).sum())
    completeness = float(found_total / expected_total) if expected_total > 0 else float("nan")

    # Auditorías
    rrep = r_stats(zeros_arr)

    dyson_stats = {"n": 0.0}
    if zeros_arr.size >= (2 * cfg.dyson_K + 1):
        F = local_dyson_force(zeros_arr, K=cfg.dyson_K)
        dyson_stats = get_stats(F)

    deficits_final = bin_deficits(zeros_arr, cfg.T0, cfg.T1, cfg.bin_width)
    deficits_final.sort(key=lambda d: d.deficit, reverse=True)
    deficits_top = [{
        "a": d.a, "b": d.b,
        "expected": float(d.expected),
        "found": int(d.found),
        "deficit": float(d.deficit),
    } for d in deficits_final[:10]]

    return {
        "range": [cfg.T0, cfg.T1],
        "expected_total": float(expected_total),
        "found_total": int(found_total),
        "completeness": float(completeness),
        "zeros_count": int(zeros_arr.size),
        "zeros": [float(x) for x in zeros_arr],
        "r_stats": rrep,
        "dyson_stats": dyson_stats,
        "deficits_top": deficits_top,
        "config": {
            "alpha_explore": cfg.alpha_explore,
            "bin_width": cfg.bin_width,
            "deficit_threshold": cfg.deficit_threshold,
            "focus_rounds": cfg.max_focus_rounds,
            "dyson_K": cfg.dyson_K,
            "dedupe": {
                "tol_abs_max": cfg.dedupe.tol_abs_max,
                "tol_gap_frac": cfg.dedupe.tol_gap_frac,
            },
            "alpha_policy": {
                "alpha_base": cfg.alpha_policy.alpha_base,
                "alpha_lupa": cfg.alpha_policy.alpha_lupa,
                "alpha_super": cfg.alpha_policy.alpha_super,
            },
        }
    }


# -----------------------------------------------------------------------------
# 6) CLI (Antigravity)
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Antigravity Lab: Rescue Miner (Explore/Focus/Verify) + mpmath Hardy Z.")
    p.add_argument("--T0", type=float, required=True)
    p.add_argument("--T1", type=float, required=True)
    p.add_argument("--alpha_explore", type=float, default=0.12)
    p.add_argument("--bin_width", type=float, default=0.5)
    p.add_argument("--deficit_threshold", type=float, default=0.10)
    p.add_argument("--focus_rounds", type=int, default=2)
    p.add_argument("--dyson_K", type=int, default=20)
    p.add_argument("--dps_base", type=int, default=50)
    p.add_argument("--dps_focus", type=int, default=80)
    p.add_argument("--out_json", type=str, default="rescue_report.json")
    p.add_argument("--no_zeros_in_json", action="store_true", help="No incluir la lista completa de ceros en el JSON.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Engine
    engine = ZEngine(EngineConfig(
        dps_base=int(args.dps_base),
        dps_focus=int(args.dps_focus),
    ))
    hooks = Hooks(
        fast_scan=engine.fast_scan,
        drill_focus=engine.drill_focus,
    )

    # Config
    cfg = RunConfig(
        T0=float(args.T0),
        T1=float(args.T1),
        alpha_explore=float(args.alpha_explore),
        bin_width=float(args.bin_width),
        deficit_threshold=float(args.deficit_threshold),
        max_focus_rounds=int(args.focus_rounds),
        dyson_K=int(args.dyson_K),
    )

    report = run_pipeline(cfg, hooks)

    if args.no_zeros_in_json:
        report.pop("zeros", None)

    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "out_json": args.out_json,
        "expected_total": report["expected_total"],
        "found_total": report["found_total"],
        "completeness": report["completeness"],
        "zeros_count": report["zeros_count"],
        "r_mean": report["r_stats"].get("r_mean", None),
        "dyson_mean": report["dyson_stats"].get("mean", None),
        "dyson_drift_slope": report["dyson_stats"].get("drift_slope", None),
        "deficits_top_0": report["deficits_top"][0] if report["deficits_top"] else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
