"""
persistence_test.py
===================
Phase-2 persistence test across three disjoint T-ranges.

Strategy:
  - Use mpmath.zetazero(n) to get mathematically exact zeros — no engine dependency.
  - Run run_probe_on_shard() on each range.
  - Produce a compact comparative table against the Phase-1 baseline.

Ranges:
  A (baseline): T in [6340, 6640]  — Phase-1 (from file, not recomputed)
  B (low):      T in [1000, 1300]  — ~ zeros 230-300
  C (mid):      T in [10000,10300] — ~ zeros 3000-3100

Falsifiability questions answered:
  1. Is sub-GUE Sigma^2 specific to T~6340, or does it appear elsewhere?
  2. Does r(log p, A_p) stay > 0.9 across ranges?
  3. Does alpha stay negative, or is it range-specific?
"""
from __future__ import annotations

import sys
import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import math
import os
import time
import numpy as np

# ── mpmath for exact zeros ────────────────────────────────────────────────────
try:
    import mpmath
    mpmath.mp.dps = 20   # 20 decimal places — more than enough
    MPMATH_OK = True
except ImportError:
    MPMATH_OK = False
    print("[ERROR] mpmath not found. Install with: pip install mpmath")
    sys.exit(1)

# ── local imports ─────────────────────────────────────────────────────────────
PROJECT   = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis"
PHASE1_FP = os.path.join(PROJECT, "results", "riemann", "jules_phase1_full.jsonl")

sys.path.insert(0, os.path.join(PROJECT, "scripts"))
from phase2_probe_recal import (
    run_probe_on_shard, Phase2Config,
    fit_prime_resonance_fixed_freq, prime_freq, _filter_primes_upto,
)


# ─────────────────────────────────────────────────────────────────────────────
# Zero acquisition
# ─────────────────────────────────────────────────────────────────────────────

def zeros_in_range(t_lo: float, t_hi: float, max_zeros: int = 200) -> np.ndarray:
    """
    Return imaginary parts of non-trivial zeta zeros in [t_lo, t_hi]
    using mpmath.zetazero(n).  Stops at max_zeros to bound runtime.
    """
    def N_approx(T):
        return (T / (2*math.pi)) * math.log(T / (2*math.pi)) - T / (2*math.pi)

    n_start = max(1, int(N_approx(t_lo)) - 5)
    zeros   = []
    n       = n_start

    print(f"  Searching zeros in T=[{t_lo},{t_hi}]  (starting at n={n_start})...",
          end="", flush=True)
    t_start_wall = time.time()

    while True:
        z = float(mpmath.im(mpmath.zetazero(n)))
        if z > t_hi + 1:
            break
        if t_lo <= z <= t_hi:
            zeros.append(z)
            if len(zeros) >= max_zeros:
                print(f" (capped at {max_zeros})", end="", flush=True)
                break
        n += 1
        if n > n_start + 3000:
            break

    elapsed = time.time() - t_start_wall
    print(f" {len(zeros)} zeros found in {elapsed:.1f}s")
    return np.array(sorted(zeros))


def load_phase1_zeros(path: str) -> np.ndarray:
    zeros = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get("t_est")
            if t is None:
                p = rec.get("payload", {})
                t = p.get("t_est") or p.get("T") or p.get("refined_T")
            if t and isinstance(t, (int, float)) and t > 0:
                zeros.append(float(t))
    return np.array(sorted(set(zeros)))


# ─────────────────────────────────────────────────────────────────────────────
# Prime-resonance correlation  r(log p, A_p)
# ─────────────────────────────────────────────────────────────────────────────

def prime_resonance_pearson(zeros: np.ndarray, primes=(2,3,5,7,11,13,17,19,23,29,31)):
    """
    Returns Pearson r(log p, A_p) from the global resonance fit.
    """
    if len(zeros) < 50:
        return float("nan"), {}

    spacings    = np.diff(zeros)
    mean_dt     = float(np.mean(spacings))
    spacings_n  = spacings / mean_dt
    x           = spacings_n - float(np.mean(spacings_n))

    A_p, phi_p, _ = fit_prime_resonance_fixed_freq(x, list(primes))

    log_p  = np.array([math.log(p) for p in primes])
    amps   = np.array([A_p[p] for p in primes])
    r_val  = float(np.corrcoef(log_p, amps)[0, 1])
    return r_val, A_p


# ─────────────────────────────────────────────────────────────────────────────
# One-range audit
# ─────────────────────────────────────────────────────────────────────────────

def audit_range(label: str, zeros: np.ndarray, cfg: Phase2Config) -> dict:
    """Run Phase-2 probe + prime correlation on a set of zeros."""
    print(f"\n  [{label}] N={len(zeros)}  T=[{zeros[0]:.1f},{zeros[-1]:.1f}]")

    if len(zeros) < cfg.window_size + 4:
        print(f"  [SKIP] Too few zeros for window_size={cfg.window_size}")
        return {"label": label, "N": len(zeros), "skipped": True}

    res    = run_probe_on_shard(zeros, cfg)
    r_pearson, A_p = prime_resonance_pearson(zeros)

    gates_str = "".join(
        ("." if v["ok"] else "X") for v in res.gates.values()
    )

    result = {
        "label":       label,
        "N":           len(zeros),
        "T_lo":        float(zeros[0]),
        "T_hi":        float(zeros[-1]),
        "S":           res.S,
        "C":           res.C,
        "alpha":       res.H,
        "sigma2":      res.sigma2_by_L,
        "r_pearson":   r_pearson,
        "A_p":         A_p,
        "gates":       gates_str,
        "skipped":     False,
    }

    # Per-L sigma2 vs GUE ratio
    for L, v in res.sigma2_by_L.items():
        gue = (1/math.pi**2) * (math.log(2*math.pi*L) + 1 + 0.5772)
        result[f"ratio_L{L}"] = v / gue if gue > 0 else float("nan")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Comparative table
# ─────────────────────────────────────────────────────────────────────────────

def print_table(results: list, sigma2_Ls=(5, 10, 20)):
    print("\n" + "="*90)
    print("  PERSISTENCE TEST — COMPARATIVE TABLE")
    print("  Baseline: Phase-1 (6340-6640). Reference: GUE.")
    print("="*90)

    # Header
    rat_headers = "  ".join(f"Sig2(L={L})/GUE" for L in sigma2_Ls)
    print(f"\n  {'Range':<22} {'N':>5}  {'S(P)':>7}  {'C':>7}  {'alpha':>7}  "
          f"{'r(logp,Ap)':>11}  {rat_headers}  {'Gates'}")
    print(f"  {'-'*88}")

    for r in results:
        if r.get("skipped"):
            print(f"  {r['label']:<22} {r['N']:>5}  {'(skipped)':>7}")
            continue

        rats = "  ".join(
            f"{r.get(f'ratio_L{L}', float('nan')):>14.1%}" for L in sigma2_Ls
        )
        print(f"  {r['label']:<22} {r['N']:>5}  {r['S']:>7.4f}  {r['C']:>7.4f}  "
              f"{r['alpha']:>7.3f}  {r['r_pearson']:>11.4f}  {rats}  [{r['gates']}]")

    # Interpretation legend
    print(f"\n  LEGEND:")
    print(f"  S(P): arith energy fraction (~0.15 global, ~0.5 per shard)")
    print(f"  C:    chaos residual (1.0 = GUE-like)")
    print(f"  alpha:  Sigma^2 ~ L^alpha  (Poisson~1, GUE~0, rigid<0)")
    print(f"  r:    Pearson(log p, A_p)  (expected ~-0.97 if explicit formula active)")
    print(f"  Gates: [Gate2 Gate3 Gate4 Gate5]  .=pass  X=fail")
    print(f"\n  FALSIFIABILITY:")
    print(f"  IF r_pearson stays < -0.9 across ranges -> explicit formula universal in studied T.")
    print(f"  IF Sigma^2 ratios stay < 1.0 across ranges -> sub-GUE is not range-specific.")
    print(f"  IF alpha stays negative -> sub-log growth is systematic.")
    print("="*90)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("="*60)
    print("  GAHENAX PHASE-2 PERSISTENCE TEST")
    print("  Ranges: [1000,1300] | [6340,6640] | [10000,10300]")
    print("="*60)

    # Config: same for all ranges for comparability
    cfg = Phase2Config(
        pmax        = 31,
        window_size = 64,    # safe for ~300 zeros
        window_step = 32,
        sigma2_L    = (5, 10, 20),
    )

    results = []

    # ── Range B: T in [1000, 1300] (low T) ───────────────────────────────────
    print("\n[1] Acquiring zeros T=[1000,1300] via mpmath...")
    zeros_B = zeros_in_range(1000.0, 1300.0)
    results.append(audit_range("B: T=[1000,1300]", zeros_B, cfg))

    # ── Range A: Phase-1 baseline (from file) ─────────────────────────────────
    print("\n[2] Loading Phase-1 baseline from file...")
    zeros_A = load_phase1_zeros(PHASE1_FP)
    results.append(audit_range("A: T=[6340,6640] baseline", zeros_A, cfg))

    # ── Range C: T in [10000, 10300] (mid T) — capped at 200 zeros ───────────
    print("\n[3] Acquiring zeros T=[10000,10300] via mpmath (cap=200)...")
    zeros_C = zeros_in_range(10000.0, 10300.0, max_zeros=200)
    results.append(audit_range("C: T=[10000,10300]", zeros_C, cfg))

    # ── Comparative table ─────────────────────────────────────────────────────
    print_table(results, sigma2_Ls=(5, 10, 20))

    # ── Save JSON summary ─────────────────────────────────────────────────────
    out_path = os.path.join(PROJECT, "results", "riemann", "persistence_test.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    save_results = []
    for r in results:
        sr = {k: v for k, v in r.items()
              if not isinstance(v, dict) or k == "sigma2"}
        # Convert sigma2 keys to str for JSON
        if "sigma2" in sr and isinstance(sr["sigma2"], dict):
            sr["sigma2"] = {str(k2): v2 for k2, v2 in sr["sigma2"].items()}
        if "A_p" in sr and isinstance(sr["A_p"], dict):
            sr["A_p"] = {str(k2): round(v2, 8) for k2, v2 in sr["A_p"].items()}
        save_results.append(sr)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"experiment": "persistence_test_phase2",
                   "date": "2026-02-22",
                   "ranges": save_results}, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved: {out_path}")
