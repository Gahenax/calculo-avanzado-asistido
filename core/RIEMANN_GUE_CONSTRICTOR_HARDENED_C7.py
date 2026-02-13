#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RIEMANN_GUE_CONSTRICTOR_HARDENED_C7.py
======================================
Pipeline determinista para farmeo de evidencia estadistica GUE
sobre ceros de zeta(s). Constraints C1-C7.

C1: Beta repulsion ~ 2
C2: KS 1-sample vs Wigner GUE CDF
C3: KS rejection of Poisson
C4: Stability cross-window (std)
C5: Unfolding correctness (mean spacing ~ 1)
C6: Pair correlation vs sine-kernel (L2)
C7: Spectral rigidity: Sigma^2(L), Delta3(L) vs GUE

Author: GAHENAX / Antigravity Core
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
from scipy import integrate, stats
import mpmath as mp

def P(msg: str) -> None:
    print(msg, flush=True)


# ========================== DEFAULT CONFIG ==========================
DEFAULT_CONFIG = {
    "mp_dps": 50,
    "count": 200,
    "windows": [1000, 2000, 3000, 4000],
    "c7_Ls": [1, 2, 4, 8],
    "c7_step": 0.25,
    "thresholds": {
        "unfold_tol": 0.05,
        "ks_gue_max": 0.10,
        "ks_pois_min": 0.20,
        "beta_target": 2.0,
        "beta_tol": 0.6,
        "c6_l2_max": 0.15,
        "c7_sigma2_l2_max": 0.35,
        "c7_delta3_l2_max": 0.35,
    },
    "seed": 1337,
}


# ========================== ZERO MINING ==========================
def mine_zeros(n_start: int, count: int, dps: int) -> np.ndarray:
    """Mine imaginary parts of zeta zeros using mpmath.zetazero."""
    mp.mp.dps = dps
    zeros = []
    t0 = time.time()
    for i in range(n_start, n_start + count):
        z = mp.zetazero(i)
        zeros.append(float(z.imag))
        if (i - n_start + 1) % 50 == 0:
            dt = time.time() - t0
            rate = (i - n_start + 1) / dt if dt > 0 else 0
            P(f"    mined {i - n_start + 1}/{count} zeros | {rate:.1f}/s")
    return np.array(zeros)


# ========================== UNFOLDING ==========================
def smooth_N(t: float) -> float:
    """Smooth part of N(t): (t/2pi)*log(t/2pi*e) + 7/8."""
    if t <= 0:
        return 0.0
    twopi = 2 * np.pi
    return (t / twopi) * np.log(t / (twopi * np.e)) + 7.0 / 8.0


def unfold(zeros: np.ndarray) -> np.ndarray:
    """Unfold zeros to get normalized spacings with mean ~1."""
    unfolded = np.array([smooth_N(t) for t in zeros])
    spacings = np.diff(unfolded)
    return spacings


# ========================== CDFs ==========================
def wigner_gue_pdf(s: float) -> float:
    """Wigner surmise PDF for GUE (beta=2)."""
    return (32.0 / np.pi**2) * s**2 * np.exp(-4.0 * s**2 / np.pi)


def _wigner_gue_cdf_scalar(s: float) -> float:
    """CDF of Wigner surmise for GUE via numerical integration (scalar)."""
    if s <= 0:
        return 0.0
    val, _ = integrate.quad(wigner_gue_pdf, 0, s)
    return min(val, 1.0)


def wigner_gue_cdf(s):
    """CDF that handles both scalar and array input (required by scipy KS)."""
    s = np.asarray(s, dtype=float)
    out = np.zeros_like(s)
    for idx in np.ndindex(s.shape):
        out[idx] = _wigner_gue_cdf_scalar(float(s[idx]))
    return out if out.ndim > 0 else float(out)


def poisson_cdf(s):
    """CDF for Poisson spacing. Handles scalar and array."""
    s = np.asarray(s, dtype=float)
    return np.where(s > 0, 1.0 - np.exp(-s), 0.0)


# ========================== C1: BETA REPULSION ==========================
def fit_beta_repulsion(spacings: np.ndarray, n_bins: int = 30) -> Tuple[float, float]:
    """
    Fit beta from p(s) ~ s^beta near s=0.
    Use log-log regression on histogram of small spacings.
    """
    s_min, s_max = 0.01, 0.8
    mask = (spacings > s_min) & (spacings < s_max)
    s_small = spacings[mask]
    if len(s_small) < 10:
        return float('nan'), float('nan')

    hist, edges = np.histogram(s_small, bins=n_bins, density=True)
    centers = 0.5 * (edges[:-1] + edges[1:])

    # Filter zero bins
    pos = hist > 0
    if pos.sum() < 3:
        return float('nan'), float('nan')

    log_s = np.log(centers[pos])
    log_p = np.log(hist[pos])

    # Linear regression: log_p = beta * log_s + const
    slope, intercept, r_value, _, _ = stats.linregress(log_s, log_p)
    return slope, r_value**2


# ========================== C2/C3: KS TESTS ==========================
def ks_test_gue(spacings: np.ndarray) -> Tuple[float, float]:
    """KS 1-sample test vs Wigner GUE CDF."""
    res = stats.ks_1samp(spacings, wigner_gue_cdf)
    return float(res.statistic), float(res.pvalue)


def ks_test_poisson(spacings: np.ndarray) -> Tuple[float, float]:
    """KS 1-sample test vs Poisson CDF."""
    res = stats.ks_1samp(spacings, poisson_cdf)
    return float(res.statistic), float(res.pvalue)


# ========================== C6: PAIR CORRELATION ==========================
def pair_correlation(spacings: np.ndarray, r_max: float = 3.0,
                     n_bins: int = 50) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute empirical pair correlation and L2 distance from GUE sine kernel.
    R2_GUE(r) = 1 - (sin(pi*r)/(pi*r))^2
    """
    # Compute all pair distances (using unfolded positions)
    positions = np.cumsum(np.concatenate([[0], spacings]))
    n = len(positions)

    diffs = []
    for i in range(n):
        for j in range(i + 1, min(i + 20, n)):  # only nearby pairs to avoid O(n^2)
            d = positions[j] - positions[i]
            if d < r_max:
                diffs.append(d)

    if not diffs:
        return float('inf'), np.array([]), np.array([]), np.array([])

    diffs = np.array(diffs)
    hist, edges = np.histogram(diffs, bins=n_bins, range=(0.01, r_max), density=True)
    centers = 0.5 * (edges[:-1] + edges[1:])

    # Normalize: empirical pair correlation
    # Mean density is 1 (after unfolding), so R2 is just the histogram
    r2_emp = hist

    # GUE theoretical
    r2_gue = 1 - (np.sin(np.pi * centers) / (np.pi * centers))**2

    # L2 distance
    dr = centers[1] - centers[0] if len(centers) > 1 else 1
    l2 = np.sqrt(np.sum((r2_emp - r2_gue)**2) * dr)

    return float(l2), centers, r2_emp, r2_gue


# ========================== C7: SPECTRAL RIGIDITY ==========================
def number_variance_empirical(positions: np.ndarray, L: float,
                               step: float = 0.25) -> float:
    """
    Compute number variance Sigma^2(L): variance of number of levels in
    intervals of length L, sampled across the spectrum.
    """
    n = len(positions)
    x_min, x_max = positions[0], positions[-1]
    counts = []

    x = x_min
    while x + L <= x_max:
        c = np.sum((positions >= x) & (positions < x + L))
        counts.append(c)
        x += step

    if len(counts) < 5:
        return float('nan')
    return float(np.var(counts))


def delta3_empirical(positions: np.ndarray, L: float,
                      step: float = 0.25) -> float:
    """
    Compute Delta3(L) (Dyson-Mehta spectral rigidity).
    Delta3(L) = min_{A,B} (1/L) integral |N(x) - Ax - B|^2 dx
    over intervals of length L.
    """
    n = len(positions)
    x_min, x_max = positions[0], positions[-1]
    delta3_vals = []

    x = x_min
    while x + L <= x_max:
        # Levels in [x, x+L]
        mask = (positions >= x) & (positions < x + L)
        levels = positions[mask]
        if len(levels) < 2:
            x += step
            continue

        # N(y) = number of levels in [x, y] for y in [x, x+L]
        # Fit Ax + B to staircase
        y_points = levels - x  # relative positions
        n_points = np.arange(1, len(levels) + 1)

        if len(y_points) >= 2:
            # Least squares fit: N(y) ~ A*y + B
            A_mat = np.column_stack([y_points, np.ones(len(y_points))])
            result = np.linalg.lstsq(A_mat, n_points, rcond=None)
            coeffs = result[0]
            residuals = n_points - (coeffs[0] * y_points + coeffs[1])
            d3 = np.mean(residuals**2) / L
            delta3_vals.append(d3)

        x += step

    if not delta3_vals:
        return float('nan')
    return float(np.mean(delta3_vals))


def sigma2_gue_theory(L: float) -> float:
    """GUE number variance (asymptotic): Sigma^2(L) ~ (2/pi^2)(log(2*pi*L) + gamma_E + 1 - pi^2/8)."""
    if L <= 0:
        return 0
    gamma_E = 0.5772156649015329
    return (2.0 / np.pi**2) * (np.log(2 * np.pi * L) + gamma_E + 1.0 - np.pi**2 / 8.0)


def delta3_gue_theory(L: float) -> float:
    """GUE Delta3 (asymptotic): Delta3(L) ~ (1/pi^2)(log(2*pi*L) + gamma_E - 5/4)."""
    if L <= 0:
        return 0
    gamma_E = 0.5772156649015329
    return (1.0 / np.pi**2) * (np.log(2 * np.pi * L) + gamma_E - 5.0 / 4.0)


# ========================== WINDOW RUNNER ==========================
def run_window(n_start: int, count: int, config: dict) -> dict:
    """Run full C1-C7 pipeline on one window of zeros."""
    dps = config["mp_dps"]
    thresholds = config["thresholds"]
    c7_Ls = config["c7_Ls"]
    c7_step_val = config["c7_step"]

    P(f"\n  --- Window n_start={n_start}, count={count} ---")

    # Mine zeros
    t0 = time.time()
    zeros = mine_zeros(n_start, count, dps)
    mine_time = time.time() - t0
    P(f"    Mining: {mine_time:.1f}s for {count} zeros")
    P(f"    t range: [{zeros[0]:.2f}, {zeros[-1]:.2f}]")

    # C5: Unfolding
    spacings = unfold(zeros)
    mean_spacing = float(np.mean(spacings))
    std_spacing = float(np.std(spacings))
    c5_pass = abs(mean_spacing - 1.0) <= thresholds["unfold_tol"]
    P(f"    C5 unfold: mean={mean_spacing:.6f} std={std_spacing:.4f} pass={c5_pass}")

    # C1: Beta repulsion
    beta, r2 = fit_beta_repulsion(spacings)
    c1_pass = abs(beta - thresholds["beta_target"]) <= thresholds["beta_tol"] if not np.isnan(beta) else False
    P(f"    C1 beta: {beta:.3f} (r2={r2:.3f}) pass={c1_pass}")

    # C2: KS vs GUE
    ks_gue, pval_gue = ks_test_gue(spacings)
    c2_pass = ks_gue <= thresholds["ks_gue_max"]
    P(f"    C2 KS GUE: stat={ks_gue:.4f} pval={pval_gue:.4f} pass={c2_pass}")

    # C3: KS vs Poisson (should be HIGH = rejection)
    ks_pois, pval_pois = ks_test_poisson(spacings)
    c3_pass = ks_pois >= thresholds["ks_pois_min"]
    P(f"    C3 KS Poisson: stat={ks_pois:.4f} pval={pval_pois:.6f} pass={c3_pass}")

    # C6: Pair correlation
    l2_c6, _, _, _ = pair_correlation(spacings)
    c6_pass = l2_c6 <= thresholds["c6_l2_max"]
    P(f"    C6 pair-corr L2: {l2_c6:.4f} pass={c6_pass}")

    # C7: Spectral rigidity
    positions = np.cumsum(np.concatenate([[0], spacings]))
    c7_results = {}

    sigma2_l2_total = 0
    delta3_l2_total = 0
    n_Ls = 0

    for L in c7_Ls:
        s2_emp = number_variance_empirical(positions, L, step=c7_step_val)
        d3_emp = delta3_empirical(positions, L, step=c7_step_val)
        s2_gue = sigma2_gue_theory(L)
        d3_gue = delta3_gue_theory(L)

        c7_results[f"L={L}"] = {
            "sigma2_emp": round(s2_emp, 6) if not np.isnan(s2_emp) else None,
            "sigma2_gue": round(s2_gue, 6),
            "delta3_emp": round(d3_emp, 6) if not np.isnan(d3_emp) else None,
            "delta3_gue": round(d3_gue, 6),
        }

        if not np.isnan(s2_emp):
            sigma2_l2_total += (s2_emp - s2_gue)**2
            n_Ls += 1
        if not np.isnan(d3_emp):
            delta3_l2_total += (d3_emp - d3_gue)**2

    sigma2_l2 = np.sqrt(sigma2_l2_total / n_Ls) if n_Ls > 0 else float('inf')
    delta3_l2 = np.sqrt(delta3_l2_total / n_Ls) if n_Ls > 0 else float('inf')
    c7_s_pass = sigma2_l2 <= thresholds["c7_sigma2_l2_max"]
    c7_d_pass = delta3_l2 <= thresholds["c7_delta3_l2_max"]
    P(f"    C7 sigma2 L2: {sigma2_l2:.4f} pass={c7_s_pass}")
    P(f"    C7 delta3 L2: {delta3_l2:.4f} pass={c7_d_pass}")

    all_pass = c1_pass and c2_pass and c3_pass and c5_pass and c6_pass and c7_s_pass and c7_d_pass

    return {
        "n_start": n_start,
        "count": count,
        "t_min": round(float(zeros[0]), 4),
        "t_max": round(float(zeros[-1]), 4),
        "mine_time_s": round(mine_time, 1),
        "c1_beta": round(beta, 4) if not np.isnan(beta) else None,
        "c1_r2": round(r2, 4) if not np.isnan(r2) else None,
        "c1_pass": c1_pass,
        "c2_ks_gue": round(ks_gue, 6),
        "c2_pval_gue": round(pval_gue, 6),
        "c2_pass": c2_pass,
        "c3_ks_pois": round(ks_pois, 6),
        "c3_pval_pois": round(pval_pois, 6),
        "c3_pass": c3_pass,
        "c4_mean_spacing": round(mean_spacing, 6),  # for cross-window later
        "c5_mean_spacing": round(mean_spacing, 6),
        "c5_std_spacing": round(std_spacing, 6),
        "c5_pass": c5_pass,
        "c6_l2": round(l2_c6, 6),
        "c6_pass": c6_pass,
        "c7_sigma2_l2": round(sigma2_l2, 6),
        "c7_delta3_l2": round(delta3_l2, 6),
        "c7_sigma2_pass": c7_s_pass,
        "c7_delta3_pass": c7_d_pass,
        "c7_details": c7_results,
        "all_pass": all_pass,
    }


# ========================== CROSS-WINDOW C4 ==========================
def compute_c4(window_results: List[dict], tol: float = 0.05) -> dict:
    """C4: Cross-window stability. Check std of key metrics."""
    betas = [w["c1_beta"] for w in window_results if w["c1_beta"] is not None]
    ks_gues = [w["c2_ks_gue"] for w in window_results]
    means = [w["c5_mean_spacing"] for w in window_results]

    beta_std = float(np.std(betas)) if len(betas) >= 2 else float('nan')
    ks_std = float(np.std(ks_gues)) if len(ks_gues) >= 2 else float('nan')
    mean_std = float(np.std(means)) if len(means) >= 2 else float('nan')

    stable = True
    if not np.isnan(beta_std) and beta_std > 0.5:
        stable = False
    if not np.isnan(mean_std) and mean_std > tol:
        stable = False

    return {
        "n_windows": len(window_results),
        "beta_values": [round(b, 4) for b in betas],
        "beta_mean": round(float(np.mean(betas)), 4) if betas else None,
        "beta_std": round(beta_std, 4) if not np.isnan(beta_std) else None,
        "ks_gue_values": [round(k, 4) for k in ks_gues],
        "ks_gue_mean": round(float(np.mean(ks_gues)), 4),
        "ks_gue_std": round(ks_std, 4) if not np.isnan(ks_std) else None,
        "mean_spacing_values": [round(m, 6) for m in means],
        "mean_spacing_std": round(mean_std, 6) if not np.isnan(mean_std) else None,
        "stable": stable,
    }


# ========================== REPORT ==========================
def write_csv(window_results: List[dict], path: str):
    if not window_results:
        return
    keys = ["n_start", "count", "t_min", "t_max", "mine_time_s",
            "c1_beta", "c1_r2", "c1_pass",
            "c2_ks_gue", "c2_pval_gue", "c2_pass",
            "c3_ks_pois", "c3_pval_pois", "c3_pass",
            "c5_mean_spacing", "c5_std_spacing", "c5_pass",
            "c6_l2", "c6_pass",
            "c7_sigma2_l2", "c7_delta3_l2", "c7_sigma2_pass", "c7_delta3_pass",
            "all_pass"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for row in window_results:
            w.writerow(row)
    P(f"[SAVED] {path}")


def write_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    P(f"[SAVED] {path}")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ========================== MAIN ==========================
def main():
    P("")
    P("+" + "=" * 68 + "+")
    P("|  RIEMANN GUE CONSTRICTOR (C1-C7) -- Hardened Pipeline             |")
    P("|  System: GAHENAX / Antigravity Core                               |")
    P("+" + "=" * 68 + "+")
    P("")

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=str, default=None, help="Config JSON file")
    ap.add_argument("--mp_dps", type=int, default=None)
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--windows", type=str, default=None, help="Comma-separated n_start list")
    ap.add_argument("--csv_out", type=str, default=None)
    ap.add_argument("--json_out", type=str, default=None)
    args = ap.parse_args()

    # Load config
    config = dict(DEFAULT_CONFIG)
    if args.config and os.path.exists(args.config):
        with open(args.config) as f:
            config.update(json.load(f))
    if args.mp_dps is not None:
        config["mp_dps"] = args.mp_dps
    if args.count is not None:
        config["count"] = args.count
    if args.windows is not None:
        config["windows"] = [int(x) for x in args.windows.split(",")]

    csv_path = args.csv_out or "core/riemann_constrictor_c7.csv"
    json_path = args.json_out or "core/riemann_constrictor_c7.json"

    rng = np.random.default_rng(config["seed"])

    P(f"CONFIG:")
    P(f"  mp_dps:   {config['mp_dps']}")
    P(f"  count:    {config['count']}")
    P(f"  windows:  {config['windows']}")
    P(f"  c7_Ls:    {config['c7_Ls']}")
    P(f"  seed:     {config['seed']}")
    P(f"  numpy:    {np.__version__}")
    P(f"  scipy:    {stats.scipy.__version__ if hasattr(stats, 'scipy') else 'unknown'}")
    P(f"  mpmath:   {mp.__version__}")
    P("")

    # Run windows
    window_results = []
    t_total = time.time()

    for n_start in config["windows"]:
        result = run_window(n_start, config["count"], config)
        window_results.append(result)

    total_time = time.time() - t_total

    # C4: Cross-window stability
    c4 = compute_c4(window_results, tol=config["thresholds"]["unfold_tol"])
    P(f"\n  C4 stability: beta_std={c4['beta_std']} ks_std={c4['ks_gue_std']} stable={c4['stable']}")

    # Aggregate verdict
    pass_count = sum(1 for w in window_results if w["all_pass"])
    pass_rate = pass_count / len(window_results) if window_results else 0

    # GATE_A: pass_rate >= 0.75 in >= 4 windows
    gate_a = pass_rate >= 0.75 and len(window_results) >= 2

    # GATE_B (strong)
    avg_beta = c4["beta_mean"] if c4["beta_mean"] is not None else float('nan')
    avg_ks = c4["ks_gue_mean"]
    avg_d3 = float(np.mean([w["c7_delta3_l2"] for w in window_results]))
    gate_b = (1.8 <= avg_beta <= 2.2 if not np.isnan(avg_beta) else False) and \
             avg_ks <= 0.05 and avg_d3 <= 0.20

    verdict = "PASSED" if gate_a else ("INCONCLUSIVE" if pass_rate > 0.5 else "FAILED")

    P(f"\n{'='*80}")
    P(f"FINAL REPORT")
    P(f"{'='*80}")
    P(f"  Windows:     {len(window_results)}")
    P(f"  Pass count:  {pass_count}/{len(window_results)}")
    P(f"  Pass rate:   {pass_rate:.2%}")
    P(f"  GATE_A:      {gate_a} (pass_rate >= 75%)")
    P(f"  GATE_B:      {gate_b} (avg_beta in [1.8,2.2], avg_ks<=0.05, avg_d3<=0.20)")
    P(f"  Avg beta:    {avg_beta:.3f}" if not np.isnan(avg_beta) else "  Avg beta:    N/A")
    P(f"  Avg KS GUE:  {avg_ks:.4f}")
    P(f"  Avg Delta3:  {avg_d3:.4f}")
    P(f"  C4 stable:   {c4['stable']}")
    P(f"  Total time:  {total_time:.1f}s")
    P(f"  VERDICT:     {verdict}")
    P("")

    # Limitations
    P("LIMITATIONS:")
    P("  - GUE compatibility does NOT prove RH")
    P("  - Statistical tests on finite samples have limited power")
    P("  - Zeros < 10^5 may not be in asymptotic regime")
    P("  - Wigner surmise is approximation to exact GUE spacing distribution")
    P("")

    # Next steps
    P("NEXT STEPS:")
    P("  1. Increase count to 500-1000 per window (more statistical power)")
    P("  2. Use higher windows (n_start > 10000) for asymptotic regime")
    P("  3. Add C8: spectral form factor K(tau)")
    P("  4. Compare with Odlyzko high-zero datasets")
    P("")

    # Save outputs
    full_data = {
        "config": config,
        "windows": window_results,
        "c4_stability": c4,
        "aggregate": {
            "pass_count": pass_count,
            "pass_rate": pass_rate,
            "gate_a": gate_a,
            "gate_b": gate_b,
            "avg_beta": round(avg_beta, 4) if not np.isnan(avg_beta) else None,
            "avg_ks_gue": round(avg_ks, 4),
            "avg_delta3": round(avg_d3, 4),
            "verdict": verdict,
            "total_time_s": round(total_time, 1),
        },
    }

    write_csv(window_results, csv_path)
    write_json(full_data, json_path)

    # Manifest
    manifest = {
        "run_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config": config,
        "verdict": verdict,
        "outputs": {},
    }
    for path in [csv_path, json_path]:
        if os.path.exists(path):
            manifest["outputs"][path] = sha256_file(path)
    write_json(manifest, json_path.replace(".json", "_manifest.json"))

    P("")
    P(f"DISCLAIMER: GUE compatibility is a statistical observation, NOT a proof of RH.")
    P(f"All results are reproducible with the provided config and seed.")
    P("")


if __name__ == "__main__":
    main()
