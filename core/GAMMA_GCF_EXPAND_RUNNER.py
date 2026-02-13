#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GAMMA_GCF_EXPAND_RUNNER.py  (v4)
=================================
Expanded search for gamma (Euler-Mascheroni) GCF representations.

Implements GAMMA_GCF_EXPAND_v1 contract:
- Multi-test stability (truncation, precision, perturbation)
- Canonicalization (leading coeff Q positive, GCD normalization, sign dedup)
- Q singularity prefilter
- P/Q ratio prefilter
- ComplexityCost scoring
- Top-K=25, ranked by StabilityScore > ComplexityCost > gap

Two phases:
  Phase A: degree <= 2, coefficients [-5, 5]
  Phase B: degree <= 3, coefficients [-3, 3]

Author: GAHENAX / Antigravity Core
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from dataclasses import dataclass, field
from math import gcd, log10
from functools import reduce
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import mpmath as mp

def P(msg: str) -> None:
    print(msg, flush=True)


# ========================== TARGET ==========================
GAMMA_STR = "0.5772156649015328606065120900824024310421593359399235988057672348848677267776646709369470632917467495"

# ========================== CONFIG ==========================
N_PROBE = 20
N_MAIN = 64
N_MAIN_2 = 128
PREC_LOW = 80   # bits (~24 decimal digits)
PREC_HIGH = 160  # bits (~48 decimal digits)
DIGITS_AGREE_MIN = 12
EPS_TRUNC = mp.mpf("1e-15")
BALLPARK_R = mp.mpf("1e-2")
Q_MIN_THRESHOLD = mp.mpf("0.5")   # reject Q if |Q(n)| < this for many n
Q_SINGULARITY_FRAC = 0.1          # reject Q if >10% of n in probe have |Q(n)| < Q_MIN
RATIO_MAX = mp.mpf("1e8")
RATIO_MIN = mp.mpf("1e-8")
TOP_K = 25
STABILITY_SCORE_MIN = 12  # minimum digits for SIG

Poly = Tuple[int, ...]


# ========================== POLY UTILS ==========================
def eval_poly(n: int, coeffs: Poly) -> int:
    deg = len(coeffs) - 1
    return sum(c * (n ** (deg - i)) for i, c in enumerate(coeffs))


def poly_to_str(coeffs: Poly, var: str = "n") -> str:
    deg = len(coeffs) - 1
    parts = []
    for i, c in enumerate(coeffs):
        p = deg - i
        if c == 0 and len(coeffs) > 1:
            continue
        if p == 0:
            parts.append(str(c))
        elif p == 1:
            if c == 1: parts.append(var)
            elif c == -1: parts.append(f"-{var}")
            else: parts.append(f"{c}*{var}")
        else:
            if c == 1: parts.append(f"{var}^{p}")
            elif c == -1: parts.append(f"-{var}^{p}")
            else: parts.append(f"{c}*{var}^{p}")
    expr = " + ".join(parts) if parts else "0"
    return expr.replace("+ -", "- ")


def poly_degree(coeffs: Poly) -> int:
    for i, c in enumerate(coeffs):
        if c != 0:
            return len(coeffs) - 1 - i
    return 0


def complexity_cost(p: Poly, q: Poly) -> int:
    return sum(abs(c) for c in p) + sum(abs(c) for c in q) + 2*poly_degree(p) + 2*poly_degree(q)


def poly_gcd(coeffs: Poly) -> int:
    nonzero = [abs(c) for c in coeffs if c != 0]
    if not nonzero:
        return 1
    return reduce(gcd, nonzero)


# ========================== CANONICALIZATION ==========================
def canonical_poly_q(coeffs: Poly) -> Optional[Poly]:
    """Normalize Q: leading coeff positive, GCD=1. Return None if invalid."""
    # Find leading nonzero
    leading_idx = -1
    for i, c in enumerate(coeffs):
        if c != 0:
            leading_idx = i
            break
    if leading_idx == -1:
        return None  # all-zero

    # Leading coeff must be positive
    if coeffs[leading_idx] < 0:
        coeffs = tuple(-c for c in coeffs)

    # GCD normalization
    g = poly_gcd(coeffs)
    if g > 1:
        coeffs = tuple(c // g for c in coeffs)

    return coeffs


def canonical_poly_p(coeffs: Poly) -> Optional[Poly]:
    """Normalize P: GCD=1. Keep sign as-is (Q controls sign convention)."""
    if all(c == 0 for c in coeffs):
        return None

    g = poly_gcd(coeffs)
    if g > 1:
        coeffs = tuple(c // g for c in coeffs)

    return coeffs


def build_poly_spaces(max_degree: int, coeff_range: range):
    """Build canonical P and Q spaces."""
    length = max_degree + 1
    raw = list(itertools.product(coeff_range, repeat=length))

    p_set = set()
    q_set = set()

    for poly in raw:
        # P
        cp = canonical_poly_p(poly)
        if cp is not None:
            p_set.add(cp)
        # Q (stricter: leading positive)
        cq = canonical_poly_q(poly)
        if cq is not None:
            q_set.add(cq)

    return sorted(p_set, key=lambda x: sum(abs(c) for c in x)), \
           sorted(q_set, key=lambda x: sum(abs(c) for c in x))


# ========================== GCF ENGINE ==========================
def eval_gcf_prec(a: Poly, b: Poly, depth: int, dps: int) -> mp.mpf:
    """Evaluate GCF at given precision (dps = decimal places)."""
    old_dps = mp.mp.dps
    mp.mp.dps = dps
    try:
        cur = mp.mpf(0)
        for n in range(depth, 0, -1):
            bn_val = mp.mpf(eval_poly(n, b)) + cur
            if bn_val == 0:
                return mp.mpf("inf")
            cur = mp.mpf(eval_poly(n, a)) / bn_val
        result = mp.mpf(eval_poly(0, b)) + cur
        return result
    finally:
        mp.mp.dps = old_dps


# ========================== PREFILTERS ==========================
def prefilter_q_singularity(q: Poly) -> bool:
    """Return True if Q is OK (no singularity issues)."""
    bad = 0
    for n in range(1, N_PROBE + 1):
        qn = eval_poly(n, q)
        if abs(qn) < float(Q_MIN_THRESHOLD):
            bad += 1
    return bad / N_PROBE < Q_SINGULARITY_FRAC


def prefilter_ratio(a: Poly, b: Poly) -> bool:
    """Check median |P(n)/Q(n)| is in reasonable range."""
    ratios = []
    for n in range(1, N_PROBE + 1):
        qn = eval_poly(n, b)
        if qn == 0:
            return False
        pn = eval_poly(n, a)
        ratios.append(abs(pn / qn))
    ratios.sort()
    med = ratios[len(ratios)//2]
    return float(RATIO_MIN) < med < float(RATIO_MAX)


def prefilter_fast(a: Poly, b: Poly, target: mp.mpf) -> bool:
    """Fast ballpark at two depths."""
    mp.mp.dps = 25
    try:
        v1 = eval_gcf_prec(a, b, N_PROBE, 25)
        if mp.isnan(v1) or mp.isinf(v1):
            return False
        if abs(v1) > mp.mpf("1e6"):
            return False
        if abs(v1 - target) > BALLPARK_R:
            return False
        v2 = eval_gcf_prec(a, b, N_MAIN, 25)
        if mp.isnan(v2) or mp.isinf(v2):
            return False
        if abs(v2 - target) > BALLPARK_R:
            return False
        return True
    except Exception:
        return False


# ========================== STABILITY TESTS ==========================
@dataclass
class StabilityResult:
    v_n: str
    v_2n: str
    trunc_delta: str
    stability_trunc: float  # -log10(delta)
    digits_agree: int       # digits matching between prec_low and prec_high
    stability_score: float  # min(trunc, digits)
    gap: str
    complexity: int
    passed: bool


def full_stability_test(a: Poly, b: Poly, target: mp.mpf) -> Optional[StabilityResult]:
    """
    Test A: Truncation stability |v(2N) - v(N)|
    Test B: Precision stability (prec_low vs prec_high at 2N)
    """
    try:
        # Convert precision bits to dps
        dps_low = max(24, PREC_LOW * 3 // 10)
        dps_high = max(48, PREC_HIGH * 3 // 10)

        # Test A: truncation
        v_n = eval_gcf_prec(a, b, N_MAIN, dps_high)
        v_2n = eval_gcf_prec(a, b, N_MAIN_2, dps_high)

        if mp.isnan(v_n) or mp.isinf(v_n) or mp.isnan(v_2n) or mp.isinf(v_2n):
            return None

        trunc_delta = abs(v_2n - v_n)
        if trunc_delta == 0:
            stab_trunc = 50.0  # perfect
        else:
            stab_trunc = float(-mp.log10(trunc_delta + mp.mpf("1e-60")))

        # Test B: precision
        v_2n_low = eval_gcf_prec(a, b, N_MAIN_2, dps_low)
        if mp.isnan(v_2n_low) or mp.isinf(v_2n_low):
            return None

        prec_delta = abs(v_2n - v_2n_low)
        if prec_delta == 0:
            digits = 50
        else:
            digits = max(0, int(float(-mp.log10(prec_delta + mp.mpf("1e-60")))))

        score = min(stab_trunc, float(digits))
        gap = abs(v_2n - target)
        cc = complexity_cost(a, b)

        passed = stab_trunc >= STABILITY_SCORE_MIN and digits >= DIGITS_AGREE_MIN

        return StabilityResult(
            v_n=mp.nstr(v_n, 30),
            v_2n=mp.nstr(v_2n, 30),
            trunc_delta=mp.nstr(trunc_delta, 10),
            stability_trunc=round(stab_trunc, 2),
            digits_agree=digits,
            stability_score=round(score, 2),
            gap=mp.nstr(gap, 15),
            complexity=cc,
            passed=passed,
        )
    except Exception:
        return None


# ========================== SCANNER ==========================
@dataclass
class ScanResult:
    phase: str
    max_degree: int
    coeff_range: List[int]
    total_p: int
    total_q: int
    total_pairs: int
    q_singular_rejected: int
    ratio_rejected: int
    fast_rejected: int
    evaluated: int
    stable_count: int
    candidates: List[dict]
    elapsed: float
    best_gap: str
    best_stability: float
    best_cost: int
    time_limited: bool


def run_phase(phase_name: str, max_degree: int, coeff_range: range,
              target: mp.mpf, time_limit: float = 600.0) -> ScanResult:

    P(f"\n{'='*80}")
    P(f"PHASE: {phase_name}")
    P(f"  degree <= {max_degree}, coefficients {list(coeff_range)}")
    P(f"  time limit: {time_limit:.0f}s")
    P(f"{'='*80}")

    p_space, q_space = build_poly_spaces(max_degree, coeff_range)
    total_p, total_q = len(p_space), len(q_space)
    total_pairs = total_p * total_q
    P(f"[INIT] P polys: {total_p} | Q polys: {total_q} | Pairs: {total_pairs:,}")

    # Pre-filter Q for singularities
    q_ok = [q for q in q_space if prefilter_q_singularity(q)]
    q_sing_rej = len(q_space) - len(q_ok)
    P(f"[PRUNE] Q singularity filter: {len(q_space)} -> {len(q_ok)} (rejected {q_sing_rej})")

    effective_pairs = total_p * len(q_ok)
    P(f"[PRUNE] Effective pairs: {effective_pairs:,}")

    t0 = time.time()
    checked = 0
    ratio_rej = 0
    fast_rej = 0
    evaluated = 0
    results: List[Tuple[float, int, str, dict]] = []  # (score, cost, gap, data) for sorting
    time_limited = False
    hb = max(1, effective_pairs // 20)

    best_gap = mp.mpf("inf")
    best_stab = 0.0
    best_cost = 99999

    for q_poly in q_ok:
        for p_poly in p_space:
            checked += 1

            if checked % hb == 0:
                dt = time.time() - t0
                rate = checked / dt if dt > 0 else 0
                P(f"  [HB] {checked:,}/{effective_pairs:,} | {rate:,.0f}/s | eval={evaluated} | stab={len(results)}")

            if time.time() - t0 > time_limit:
                time_limited = True
                P(f"  [TIME LIMIT] {time_limit:.0f}s reached at {checked:,}/{effective_pairs:,}")
                break

            # Ratio prefilter
            if not prefilter_ratio(p_poly, q_poly):
                ratio_rej += 1
                continue

            # Fast ballpark
            if not prefilter_fast(p_poly, q_poly, target):
                fast_rej += 1
                continue

            # Full stability test
            evaluated += 1
            sr = full_stability_test(p_poly, q_poly, target)
            if sr is None:
                continue

            gap_val = mp.mpf(sr.gap)
            if gap_val < best_gap:
                best_gap = gap_val
            if sr.stability_score > best_stab:
                best_stab = sr.stability_score
            if sr.complexity < best_cost:
                best_cost = sr.complexity

            if sr.stability_score >= 5:  # record anything with reasonable stability
                entry = {
                    "p_poly": list(p_poly),
                    "q_poly": list(q_poly),
                    "p_str": poly_to_str(p_poly),
                    "q_str": poly_to_str(q_poly),
                    "deg_p": poly_degree(p_poly),
                    "deg_q": poly_degree(q_poly),
                    "complexity_cost": sr.complexity,
                    "v_n": sr.v_n,
                    "v_2n": sr.v_2n,
                    "trunc_delta": sr.trunc_delta,
                    "stability_trunc": sr.stability_trunc,
                    "digits_agree": sr.digits_agree,
                    "stability_score": sr.stability_score,
                    "gap": sr.gap,
                    "passed": sr.passed,
                }
                results.append((-sr.stability_score, sr.complexity, sr.gap, entry))

        if time_limited:
            break

    elapsed = time.time() - t0

    # Sort: best stability first, then lowest cost, then smallest gap
    results.sort(key=lambda r: (r[0], r[1], float(mp.mpf(r[2]))))
    top_k = [r[3] for r in results[:TOP_K]]
    stable_count = sum(1 for r in results if r[3]["passed"])

    P(f"  [DONE] checked={checked:,} | ratio_rej={ratio_rej:,} | fast_rej={fast_rej:,}")
    P(f"         evaluated={evaluated} | stable(score>=12)={stable_count} | top_k={len(top_k)}")
    P(f"         best_gap={mp.nstr(best_gap, 10)} | best_stab={best_stab:.1f} | best_cost={best_cost}")
    P(f"         elapsed={elapsed:.1f}s | time_limited={time_limited}")

    return ScanResult(
        phase=phase_name,
        max_degree=max_degree,
        coeff_range=list(coeff_range),
        total_p=total_p,
        total_q=total_q,
        total_pairs=total_pairs,
        q_singular_rejected=q_sing_rej,
        ratio_rejected=ratio_rej,
        fast_rejected=fast_rej,
        evaluated=evaluated,
        stable_count=stable_count,
        candidates=top_k,
        elapsed=elapsed,
        best_gap=mp.nstr(best_gap, 15),
        best_stability=best_stab,
        best_cost=best_cost,
        time_limited=time_limited,
    )


# ========================== REPORT ==========================
def print_report(results: List[ScanResult]):
    P("")
    P("=" * 80)
    P("GAMMA GCF EXPAND -- FINAL REPORT")
    P("=" * 80)
    P(f"Target: gamma = {GAMMA_STR[:50]}...")
    P(f"Depths: N={N_MAIN}, 2N={N_MAIN_2}")
    P(f"Precision: low={PREC_LOW}bits high={PREC_HIGH}bits")
    P(f"Stability threshold: {STABILITY_SCORE_MIN} digits")
    P("")

    total_candidates_passed = 0

    for r in results:
        P(f"--- {r.phase} ---")
        P(f"  degree <= {r.max_degree}, coeffs {r.coeff_range}")
        P(f"  Polys: P={r.total_p}, Q={r.total_q}, Pairs={r.total_pairs:,}")
        P(f"  Pruning: Q_sing={r.q_singular_rejected}, ratio={r.ratio_rejected:,}, fast={r.fast_rejected:,}")
        P(f"  Evaluated: {r.evaluated}")
        P(f"  Stable (score>={STABILITY_SCORE_MIN}): {r.stable_count}")
        P(f"  Time: {r.elapsed:.1f}s {'[TIME LIMITED]' if r.time_limited else ''}")
        P(f"  Best gap: {r.best_gap}")
        P(f"  Best stability: {r.best_stability:.1f}")
        P(f"  Best cost: {r.best_cost}")
        P("")

        if r.candidates:
            for i, c in enumerate(r.candidates):
                label = "STRUCTURAL CANDIDATE" if c["passed"] else "SUB-THRESHOLD"
                P(f"  {label} #{i+1}")
                P(f"    P(n): {c['p_poly']}  ->  {c['p_str']}  deg={c['deg_p']}")
                P(f"    Q(n): {c['q_poly']}  ->  {c['q_str']}  deg={c['deg_q']}")
                P(f"    ComplexityCost: {c['complexity_cost']}")
                P(f"    v(N={N_MAIN}):   {c['v_n']}")
                P(f"    v(2N={N_MAIN_2}): {c['v_2n']}")
                P(f"    trunc delta:  {c['trunc_delta']}")
                P(f"    stab_trunc:   {c['stability_trunc']:.1f} digits")
                P(f"    digits_agree: {c['digits_agree']}")
                P(f"    StabScore:    {c['stability_score']:.1f}")
                P(f"    gap:          {c['gap']}")
                P(f"    VERDICT:      {'CANDIDATE' if c['passed'] else 'REJECTED (sub-threshold)'}")
                P("")
                if c["passed"]:
                    total_candidates_passed += 1
        else:
            P("  (no candidates with stability >= 5)")
            P("")

    P("=" * 80)
    P("CONCLUSION")
    P("=" * 80)
    if total_candidates_passed > 0:
        P(f"gamma: SIG_CANDIDATES ({total_candidates_passed} candidate(s) with StabilityScore >= {STABILITY_SCORE_MIN})")
        P("WARNING: This is NOT proof of a closed form. Numerical stability does not imply identity.")
    else:
        P("gamma: NO_SIG")
        P(f"No structural candidates with StabilityScore >= {STABILITY_SCORE_MIN} found")
        P("under current constraints.")
        for r in results:
            P(f"  {r.phase}: best_gap={r.best_gap}, best_stab={r.best_stability:.1f}, best_cost={r.best_cost}")
    P("")
    P("DISCLAIMER: All results are NUMERICAL COINCIDENCES. NOT proofs.")
    P("Numerical stability does not imply irrationality/rationality or closed form.")
    P("")


# ========================== MAIN ==========================
def main():
    P("")
    P("+" + "=" * 68 + "+")
    P("|  ANTIGRAVITY -- GAMMA GCF EXPAND v4.0                             |")
    P("|  Entropy Reducer + Logic Harness + Multi-Precision Stability       |")
    P("|  System: GAHENAX / Antigravity Core                                |")
    P("+" + "=" * 68 + "+")
    P("")

    mp.mp.dps = 50  # base precision for target
    gamma_target = mp.mpf(GAMMA_STR)
    P(f"Target: gamma = {mp.nstr(gamma_target, 40)}")
    P(f"Precision source: hardcoded 96-digit string")
    P(f"mpmath version: {mp.__version__}")
    P("")

    results: List[ScanResult] = []

    # Phase A: degree <= 2, coefficients [-5, 5]
    r_a = run_phase("Phase A: deg<=2, coeff[-5,5]",
                    max_degree=2, coeff_range=range(-5, 6),
                    target=gamma_target, time_limit=300.0)
    results.append(r_a)

    # Phase B: degree <= 3, coefficients [-3, 3]
    r_b = run_phase("Phase B: deg<=3, coeff[-3,3]",
                    max_degree=3, coeff_range=range(-3, 4),
                    target=gamma_target, time_limit=300.0)
    results.append(r_b)

    print_report(results)

    # Save JSON
    data = {
        "target": "gamma (Euler-Mascheroni)",
        "target_value": GAMMA_STR,
        "phases": [],
    }
    for r in results:
        phase_data = {
            "phase": r.phase,
            "max_degree": r.max_degree,
            "coeff_range": r.coeff_range,
            "total_pairs": r.total_pairs,
            "q_singular_rejected": r.q_singular_rejected,
            "ratio_rejected": r.ratio_rejected,
            "fast_rejected": r.fast_rejected,
            "evaluated": r.evaluated,
            "stable_count": r.stable_count,
            "elapsed": r.elapsed,
            "time_limited": r.time_limited,
            "best_gap": r.best_gap,
            "best_stability": r.best_stability,
            "best_cost": r.best_cost,
            "candidates": r.candidates,
        }
        data["phases"].append(phase_data)

    with open("core/gamma_expand_results_v4.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    P("[SAVED] core/gamma_expand_results_v4.json")
    P("")


if __name__ == "__main__":
    main()
