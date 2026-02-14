#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RIEMANN_FINAL_VERDICT_ONEPROMPT.py
==================================
Auditoria estadistica "final" (operativa, defendible, reproducible) para la firma GUE
en ceros de zeta (altura asintotica).

Incluye TODO (un solo archivo):
- Mining de ceros con mpmath.zetazero
- Unfolding Riemann-von Mangoldt N(T) + normalizacion local de spacings (mean=1)
- Metricas por bloque: Gap Ratio, Beta MLE, SFF (raw) + distancias a controles
- Controles sinteticos CORREGIDOS:
  * GUE: eigenvalores Hermiticos complejos, bulk window, spacings reales, tamano EXACTO
  * Poisson: spacings exponenciales, tamano EXACTO
  * Promedio multi-seed para estabilizar benchmark
- Bootstrapping CI 95%
- Voting: GUE vote rate (d_GUE < d_Poi)
- Veredicto: CONFIRMED_GUE_UNIVERSALITY si vote_rate >= 95% y CI apoyan GUE

Autor: GAHENAX Core
"""

import sys
import json
import argparse
from typing import Tuple, Dict, Any, List, Optional

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import gamma as Gamma

try:
    from mpmath import mp
except ImportError:
    print("CRITICAL: Requiere 'mpmath' (pip install mpmath).")
    sys.exit(1)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# =============================================================================
# 1) METRICAS CORTO ALCANCE
# =============================================================================

def gap_ratio(levels: np.ndarray) -> float:
    levels = np.asarray(levels, dtype=float)
    deltas = np.diff(levels)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0)]
    if deltas.size < 10:
        return float("nan")
    r = np.minimum(deltas[:-1], deltas[1:]) / np.maximum(deltas[:-1], deltas[1:])
    return float(np.mean(r))


def wigner_beta_logpdf(s: np.ndarray, beta: float) -> np.ndarray:
    s = np.clip(s, 1e-15, np.inf)
    num = Gamma((beta + 2.0) / 2.0)
    den = Gamma((beta + 1.0) / 2.0)
    b = (num / den) ** 2
    a = 2.0 * (b ** ((beta + 1.0) / 2.0)) / den
    return np.log(a) + beta * np.log(s) - b * (s ** 2)


def estimate_beta_mle(spacings: np.ndarray, min_n: int = 50) -> float:
    x = np.asarray(spacings, dtype=float)
    x = x[np.isfinite(x) & (x > 1e-12)]
    if x.size < min_n:
        return float("nan")

    # mean=1
    x = x / np.mean(x)

    # robust tail clip
    x = x[(x < 8.0)]
    if x.size < min_n:
        return float("nan")

    def nll(beta: float) -> float:
        return -float(np.sum(wigner_beta_logpdf(x, beta)))

    res = minimize_scalar(nll, bounds=(0.0, 5.0), method="bounded")
    return float(res.x) if res.success else float("nan")


# =============================================================================
# 2) UNFOLDING RIEMANN-VON MANGOLDT
# =============================================================================

def riemann_von_mangoldt_N(T: np.ndarray) -> np.ndarray:
    T = np.asarray(T, dtype=float)
    x = np.clip(T / (2.0 * np.pi), 1e-300, np.inf)
    return x * np.log(x) - x + 7.0 / 8.0


def unfold_zeros_by_N(zeros_imag: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    T = np.asarray(zeros_imag, dtype=float)
    U = riemann_von_mangoldt_N(T)
    spacings = np.diff(U)
    spacings = spacings / np.mean(spacings)  # local mean=1
    levels_u = np.concatenate(([0.0], np.cumsum(spacings)))
    return levels_u, spacings


# =============================================================================
# 3) SFF (RAW) + DISTANCIA
# =============================================================================

def sff_raw(levels_unfolded: np.ndarray, taus: np.ndarray) -> np.ndarray:
    x = np.asarray(levels_unfolded, dtype=float)
    x = x[np.isfinite(x)]
    N = x.size
    if N < 50:
        return np.full_like(taus, np.nan, dtype=float)

    K = np.zeros_like(taus, dtype=float)
    for i, tau in enumerate(taus):
        phases = 2.0 * np.pi * tau * x
        z = np.sum(np.exp(1j * phases))
        K[i] = (np.abs(z) ** 2) / N
    return K


def sff_distance(K_a: np.ndarray, K_b: np.ndarray) -> float:
    mask = np.isfinite(K_a) & np.isfinite(K_b)
    if not np.any(mask):
        return float("nan")
    return float(np.sqrt(np.mean((K_a[mask] - K_b[mask]) ** 2)))


# =============================================================================
# 4) CONTROLES SINTETICOS (GUE vs POISSON) - MATCH EXACTO DE TAMANO
# =============================================================================

def unfold_gue_bulk_exact(w: np.ndarray, out_n: int, trim: float = 0.10) -> np.ndarray:
    w = np.asarray(w, dtype=float)
    w = w[np.isfinite(w)]
    w.sort()
    N = w.size
    if N < out_n + 2:
        raise ValueError("Eigenvalue array too small for requested out_n.")

    lo = int(trim * N)
    hi = int((1.0 - trim) * N)
    if hi - lo < out_n + 2:
        lo, hi = 0, N

    wb = w[lo:hi]
    if wb.size < out_n + 2:
        wb = w

    start = max(0, (wb.size - out_n) // 2)
    wc = wb[start:start + out_n]

    s = np.diff(wc)
    s = s[np.isfinite(s) & (s > 0)]
    if s.size < out_n - 1:
        wc = np.unique(wc)
        if wc.size < out_n:
            raise ValueError("Not enough unique eigenvalues after cleanup.")
        wc = wc[:out_n]
        s = np.diff(wc)

    s = s / np.mean(s)
    levels = np.concatenate(([0.0], np.cumsum(s)))

    if levels.size != out_n:
        levels = levels[:out_n]
        if levels.size < out_n:
            levels = np.pad(levels, (0, out_n - levels.size), mode="edge")
    return levels


def generate_gue_levels_exact(N_out: int, seed: int = 0, trim: float = 0.10) -> np.ndarray:
    N_in = int(np.ceil(1.35 * N_out))
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(N_in, N_in)) + 1j * rng.normal(size=(N_in, N_in))
    H = (A + A.conj().T) / 2.0
    w = np.linalg.eigvalsh(H).real
    return unfold_gue_bulk_exact(w, out_n=N_out, trim=trim)


def generate_poisson_levels_exact(N_out: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spacings = rng.exponential(scale=1.0, size=N_out - 1)
    return np.concatenate(([0.0], np.cumsum(spacings)))


def mean_control_K(kind: str, block_size: int, taus: np.ndarray,
                   seeds: List[int], trim: float = 0.10) -> np.ndarray:
    Ks = []
    for sd in seeds:
        if kind.upper() == "GUE":
            levels = generate_gue_levels_exact(block_size, seed=sd, trim=trim)
        else:
            levels = generate_poisson_levels_exact(block_size, seed=sd)
        Ks.append(sff_raw(levels, taus))
    return np.nanmean(np.stack(Ks, axis=0), axis=0)


def generate_controls(block_size: int, taus: np.ndarray,
                      seeds: List[int], trim: float = 0.10) -> Dict[str, Any]:
    print(f"[CONTROLS] Generating GUE ({len(seeds)} seeds, N_in~{int(1.35*block_size)})...", flush=True)
    K_gue = mean_control_K("GUE", block_size, taus, seeds=seeds, trim=trim)
    print(f"[CONTROLS] Generating Poisson ({len(seeds)} seeds)...", flush=True)
    K_poi = mean_control_K("POISSON", block_size, taus, seeds=seeds, trim=trim)
    return {"GUE": {"K": K_gue}, "Poisson": {"K": K_poi},
            "seeds": list(seeds), "trim": float(trim)}


# =============================================================================
# 5) BLOQUES + BOOTSTRAP + VOTO
# =============================================================================

def block_metrics(
    zeros_block: np.ndarray,
    taus: np.ndarray,
    K_gue: np.ndarray,
    K_poi: np.ndarray,
) -> Dict[str, Any]:
    levels_u, spacings = unfold_zeros_by_N(zeros_block)
    gr = gap_ratio(levels_u)
    beta = estimate_beta_mle(spacings)
    K = sff_raw(levels_u, taus)
    d_gue = sff_distance(K, K_gue)
    d_poi = sff_distance(K, K_poi)
    vote = "GUE_CLOSER" if d_gue < d_poi else "POISSON_CLOSER"
    return {"gap_ratio": gr, "beta_mle": beta, "d_gue": d_gue, "d_poi": d_poi, "vote": vote}


def make_blocks(zeros: np.ndarray, block_size: int,
                mode: str = "disjoint") -> List[np.ndarray]:
    zeros = np.asarray(zeros, dtype=float)
    if block_size <= 1 or block_size > zeros.size:
        return []
    step = max(1, block_size // 2) if mode == "overlap50" else block_size
    return [zeros[i:i + block_size]
            for i in range(0, zeros.size - block_size + 1, step)]


def bootstrap_ci(x: np.ndarray, n_boot: int = 2000,
                 alpha: float = 0.05, seed: int = 0) -> Tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return (float("nan"), float("nan"), float("nan"))

    boots = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        samp = rng.choice(x, size=x.size, replace=True)
        boots[b] = float(np.mean(samp))
    lo = float(np.quantile(boots, alpha / 2.0))
    hi = float(np.quantile(boots, 1.0 - alpha / 2.0))
    return (float(np.mean(x)), lo, hi)


def audit_blocks(
    zeros: np.ndarray,
    taus: np.ndarray,
    controls: Dict[str, Any],
    block_size: int,
    block_mode: str,
    vote_threshold: float,
    n_boot: int,
) -> Dict[str, Any]:
    print(f"[AUDIT] blocks: size={block_size}, mode={block_mode}", flush=True)
    blocks = make_blocks(zeros, block_size, mode=block_mode)
    if not blocks:
        return {"error": "No blocks produced. Check block_size vs total_zeros."}

    K_gue = controls["GUE"]["K"]
    K_poi = controls["Poisson"]["K"]

    metrics = []
    for idx, zb in enumerate(blocks):
        m = block_metrics(zb, taus, K_gue, K_poi)
        m["block_idx"] = idx
        metrics.append(m)
        print(f"  block {idx}: gr={m['gap_ratio']:.4f} beta={m['beta_mle']:.3f} "
              f"d_gue={m['d_gue']:.3f} d_poi={m['d_poi']:.3f} => {m['vote']}", flush=True)

    grs = np.array([m["gap_ratio"] for m in metrics], dtype=float)
    betas = np.array([m["beta_mle"] for m in metrics], dtype=float)
    dg = np.array([m["d_gue"] for m in metrics], dtype=float)
    dp = np.array([m["d_poi"] for m in metrics], dtype=float)
    votes = np.array([m["vote"] for m in metrics], dtype=object)

    gue_rate = float(np.mean(votes == "GUE_CLOSER"))

    gr_mean, gr_lo, gr_hi = bootstrap_ci(grs, n_boot=n_boot, seed=1)
    b_mean, b_lo, b_hi = bootstrap_ci(betas, n_boot=n_boot, seed=2)
    dg_mean, dg_lo, dg_hi = bootstrap_ci(dg, n_boot=n_boot, seed=3)
    dp_mean, dp_lo, dp_hi = bootstrap_ci(dp, n_boot=n_boot, seed=4)

    verdict = "INCONCLUSIVE"
    if gue_rate >= vote_threshold and gr_lo > 0.50 and b_lo > 1.50:
        verdict = "CONFIRMED_GUE_UNIVERSALITY"
    elif gue_rate <= (1.0 - vote_threshold) and gr_hi < 0.45 and b_hi < 0.50:
        verdict = "CONFIRMED_POISSON"

    return {
        "config": {
            "block_size": int(block_size),
            "block_mode": block_mode,
            "n_blocks": int(len(blocks)),
            "vote_threshold": float(vote_threshold),
            "bootstrap": {"n_boot": int(n_boot), "alpha": 0.05},
            "taus": {"min": float(np.min(taus)), "max": float(np.max(taus)),
                     "M": int(taus.size)},
        },
        "verdict": verdict,
        "gue_vote_rate": gue_rate,
        "stats": {
            "gap_ratio": {"mean": gr_mean, "CI95": [gr_lo, gr_hi],
                          "targets": {"GUE": 0.60, "Poisson": 0.386}},
            "beta_mle":  {"mean": b_mean,  "CI95": [b_lo, b_hi],
                          "targets": {"GUE": 2.0,  "Poisson": 0.0}},
            "dist_gue":  {"mean": dg_mean, "CI95": [dg_lo, dg_hi]},
            "dist_poi":  {"mean": dp_mean, "CI95": [dp_lo, dp_hi]},
        },
        "per_block": metrics,
    }


# =============================================================================
# 6) MINER + ORQUESTADOR
# =============================================================================

def fetch_zeros(n_start: int, count: int) -> np.ndarray:
    print(f"[MINING] Fetching {count} zeros starting at n={n_start}...", flush=True)
    zeros = np.empty(count, dtype=float)
    step = max(1, count // 10)
    for i in range(count):
        zeros[i] = float(mp.zetazero(n_start + i).imag)
        if (i + 1) % step == 0 or (i + 1) == count:
            print(f"  ..{i+1}/{count}", flush=True)
    return zeros


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Riemann Zeta Quantum Chaos Final Verdict (One Prompt)")
    p.add_argument("--n_start", type=int, default=5000)
    p.add_argument("--total_zeros", type=int, default=2000)
    p.add_argument("--block_size", type=int, default=200)
    p.add_argument("--block_mode", type=str, default="disjoint",
                   choices=["disjoint", "overlap50"])
    p.add_argument("--mp_dps", type=int, default=50)
    p.add_argument("--taus_min", type=float, default=0.01)
    p.add_argument("--taus_max", type=float, default=2.00)
    p.add_argument("--taus_M", type=int, default=100)
    p.add_argument("--vote_threshold", type=float, default=0.95)
    p.add_argument("--n_boot", type=int, default=2000)
    p.add_argument("--control_seeds", type=str,
                   default="41,42,43,44,45,46,47,48")
    p.add_argument("--gue_trim", type=float, default=0.10)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    mp.dps = args.mp_dps

    print(f"\n{'+'+'='*68+'+'}", flush=True)
    print(f"|  RIEMANN FINAL VERDICT -- GUE Universality Audit                 |", flush=True)
    print(f"|  System: GAHENAX / Antigravity Core                              |", flush=True)
    print(f"{'+'+'='*68+'+'}\n", flush=True)

    print(f"CONFIG:", flush=True)
    print(f"  n_start={args.n_start}, total_zeros={args.total_zeros}", flush=True)
    print(f"  block_size={args.block_size}, block_mode={args.block_mode}", flush=True)
    print(f"  mp_dps={args.mp_dps}", flush=True)
    print(f"  taus: [{args.taus_min}, {args.taus_max}] x {args.taus_M}", flush=True)
    print(f"  vote_threshold={args.vote_threshold}", flush=True)
    print(f"  n_boot={args.n_boot}", flush=True)
    print(f"  control_seeds={args.control_seeds}", flush=True)
    import mpmath as _mpmath_mod
    print(f"  numpy={np.__version__}, mpmath={_mpmath_mod.__version__}", flush=True)
    print("", flush=True)

    taus = np.linspace(args.taus_min, args.taus_max, args.taus_M)

    seeds = [int(s.strip()) for s in args.control_seeds.split(",") if s.strip()]
    if not seeds:
        seeds = [42]

    zeros = fetch_zeros(args.n_start, args.total_zeros)

    print("[CONTROLS] Building controls (multi-seed mean)...", flush=True)
    controls = generate_controls(args.block_size, taus, seeds=seeds,
                                 trim=args.gue_trim)

    report = audit_blocks(
        zeros=zeros,
        taus=taus,
        controls=controls,
        block_size=args.block_size,
        block_mode=args.block_mode,
        vote_threshold=args.vote_threshold,
        n_boot=args.n_boot,
    )

    report["meta"] = {
        "n_start": int(args.n_start),
        "total_zeros": int(args.total_zeros),
        "block_size": int(args.block_size),
        "block_mode": args.block_mode,
        "mp_dps": int(args.mp_dps),
        "control": {"seeds": controls["seeds"], "gue_trim": controls["trim"]},
        "targets": "GUE: gap_ratio~0.60, beta~2.0, SFF closer to GUE than Poisson.",
        "decision_rule": "CONFIRMED_GUE_UNIVERSALITY if vote_rate>=threshold and CIs support.",
    }

    # Save JSON
    json_path = "core/riemann_final_verdict.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[SAVED] {json_path}", flush=True)

    print(f"\n{'='*80}", flush=True)
    print(f"FINAL AUDIT VERDICT", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"  Verdict:        {report['verdict']}", flush=True)
    print(f"  GUE vote rate:  {report['gue_vote_rate']:.2%}", flush=True)
    s = report["stats"]
    print(f"  Gap Ratio:      {s['gap_ratio']['mean']:.4f} "
          f"CI95=[{s['gap_ratio']['CI95'][0]:.4f}, {s['gap_ratio']['CI95'][1]:.4f}] "
          f"(GUE~0.60, Poi~0.39)", flush=True)
    print(f"  Beta MLE:       {s['beta_mle']['mean']:.3f} "
          f"CI95=[{s['beta_mle']['CI95'][0]:.3f}, {s['beta_mle']['CI95'][1]:.3f}] "
          f"(GUE~2.0, Poi~0.0)", flush=True)
    print(f"  d(R,GUE):       {s['dist_gue']['mean']:.4f} "
          f"CI95=[{s['dist_gue']['CI95'][0]:.4f}, {s['dist_gue']['CI95'][1]:.4f}]", flush=True)
    print(f"  d(R,Poisson):   {s['dist_poi']['mean']:.4f} "
          f"CI95=[{s['dist_poi']['CI95'][0]:.4f}, {s['dist_poi']['CI95'][1]:.4f}]", flush=True)
    print("", flush=True)

    if report.get("verdict") == "CONFIRMED_GUE_UNIVERSALITY":
        print("[SYSTEM] PASSED: Riemann zeros estadisticamente indistinguibles "
              "de universalidad GUE (bajo este pipeline).", flush=True)
        print("", flush=True)
        print("DISCLAIMER: Statistical compatibility != proof of RH.", flush=True)
        print("This is a reproducible statistical observation, not a theorem.", flush=True)
        return 0
    if report.get("verdict") == "CONFIRMED_POISSON":
        print("[SYSTEM] PASSED (Poisson): comportamiento integrable detectado.", flush=True)
        return 0

    print("[SYSTEM] INCONCLUSIVE: increase total_zeros, adjust block_size, "
          "or use overlap50.", flush=True)
    print("", flush=True)
    print("DISCLAIMER: Statistical compatibility != proof of RH.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
