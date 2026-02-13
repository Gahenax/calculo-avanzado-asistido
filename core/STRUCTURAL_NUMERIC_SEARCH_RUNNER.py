#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STRUCTURAL_NUMERIC_SEARCH_RUNNER.py  (v2 -- Logic Harness Edition)
===================================================================
Implements the full ANTIGRAVITY Logic Harness Protocol v1.0.

STEPS EXECUTED:
  0  SPEC            -- restate targets, structure class, bounds
  1  FAILURE MODES   -- explicit checklist
  2  TEST PLAN       -- multi-depth, tail sensitivity, cross-check, calibration
  3  SEARCH STRATEGY -- cheap filter + full pipeline, stats tracking
  4  OUTPUT CONTRACT -- strict per-candidate report
  5  NO HYPE CLOSURE -- conservative summary

Optimizations vs v1:
  - Precision 30 dps (sufficient for discovery-phase exploration)
  - Coefficients [-2, 2] (search space ~15k pairs)
  - Flushed output for real-time monitoring
  - Tail sensitivity + cross-check gates added

Author: GAHENAX / Antigravity Core
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Fix Windows console encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import mpmath as mp

# ========================== STEP 0: SPEC ==========================
PRECISION_DPS = 30
mp.mp.dps = PRECISION_DPS

MAX_DEGREE = 2
COEFF_RANGE = range(-2, 3)  # [-2, -1, 0, 1, 2]

# Depth schedule: N, 2N, 4N, 8N
DEPTHS: Tuple[int, ...] = (40, 80, 160, 320)

STABILITY_EPS = mp.mpf("1e-20")
FAST_DEPTH = 15
FAST_BALLPARK = mp.mpf("1e-2")
CANDIDATE_TOL = mp.mpf("1e-10")

# Tail sensitivity: perturb last k terms
TAIL_K = 5
TAIL_PERTURB = mp.mpf("1e-6")
TAIL_THRESHOLD = mp.mpf("1e-8")  # max change allowed

# Cross-check: compare vs target +/- eps
CROSS_EPS = mp.mpf("1e-4")

TOP_K = 5

Poly = Tuple[int, ...]
mpf = mp.mpf


def P(msg: str) -> None:
    """Print with immediate flush."""
    print(msg, flush=True)


# ========================== ENGINE ==========================
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


def eval_gcf(a: Poly, b: Poly, depth: int) -> mpf:
    cur = mp.mpf(0)
    for n in range(depth, 0, -1):
        bn_val = mp.mpf(eval_poly(n, b)) + cur
        if bn_val == 0:
            return mp.mpf("inf")
        cur = mp.mpf(eval_poly(n, a)) / bn_val
    return mp.mpf(eval_poly(0, b)) + cur


def eval_gcf_perturbed(a: Poly, b: Poly, depth: int, k: int, eps: mpf) -> mpf:
    """Evaluate GCF but add eps to the last k a(n) terms (tail sensitivity)."""
    cur = mp.mpf(0)
    for n in range(depth, 0, -1):
        an = eval_poly(n, a)
        if n > depth - k:
            an = an + float(eps)
        bn_val = mp.mpf(eval_poly(n, b)) + cur
        if bn_val == 0:
            return mp.mpf("inf")
        cur = mp.mpf(an) / bn_val
    return mp.mpf(eval_poly(0, b)) + cur


# ========================== TEST GATES ==========================
@dataclass
class TestResults:
    # Multi-depth
    values: List[str]
    deltas: List[str]
    stability_score: str
    stability_pass: bool
    # Tail sensitivity
    tail_metric: str
    tail_pass: bool
    # Cross-check
    cross_metric: str
    cross_pass: bool


def gate_multidepth(a: Poly, b: Poly) -> Optional[Tuple[mpf, List[mpf], List[mpf]]]:
    vals = []
    for d in DEPTHS:
        v = eval_gcf(a, b, d)
        if mp.isnan(v) or mp.isinf(v):
            return None
        vals.append(v)

    deltas = [abs(vals[i+1] - vals[i]) for i in range(len(vals)-1)]
    score = max(deltas) if deltas else mp.mpf("inf")

    # Check deltas are decreasing (no oscillation)
    for i in range(len(deltas)-1):
        if deltas[i+1] > deltas[i] * 10:
            return None

    if score > STABILITY_EPS:
        return None

    return vals[-1], vals, deltas


def gate_tail_sensitivity(a: Poly, b: Poly, base_value: mpf) -> Tuple[bool, mpf]:
    v_pert = eval_gcf_perturbed(a, b, DEPTHS[-1], TAIL_K, TAIL_PERTURB)
    if mp.isnan(v_pert) or mp.isinf(v_pert):
        return False, mp.mpf("inf")
    delta = abs(v_pert - base_value)
    return delta < TAIL_THRESHOLD, delta


def gate_cross_check(a: Poly, b: Poly, target: mpf) -> Tuple[bool, mpf]:
    """Ensure this structure is NOT equally close to target +/- eps."""
    v = eval_gcf(a, b, DEPTHS[-1])
    err_target = abs(v - target)
    err_plus = abs(v - (target + CROSS_EPS))
    err_minus = abs(v - (target - CROSS_EPS))

    # The candidate should be significantly closer to target than to shifted targets
    ratio = min(err_plus, err_minus) / err_target if err_target > 0 else mp.mpf(0)
    # ratio >> 1 means target is special; ratio ~1 means structure just happens to be near
    return ratio > mp.mpf("5"), ratio


# ========================== FULL PIPELINE ==========================
@dataclass
class FullCandidate:
    target_name: str
    target_value: str
    a_poly: Poly
    b_poly: Poly
    a_str: str
    b_str: str
    approximation: str
    depths: List[int]
    values: List[str]
    deltas: List[str]
    stability_score: str
    abs_error: str
    rel_error: str
    tail_pass: bool
    tail_metric: str
    cross_pass: bool
    cross_metric: str
    verdict: str
    discard_condition: str
    rank: int = 0


class LogicHarnessScanner:
    def __init__(self):
        raw = list(itertools.product(COEFF_RANGE, repeat=MAX_DEGREE + 1))
        self.poly_space: List[Poly] = [p for p in raw if any(x != 0 for x in p)]
        self.total = len(self.poly_space) ** 2
        self.stats = {"fast_rejected": 0, "stability_rejected": 0, "tol_rejected": 0,
                      "tail_rejected": 0, "cross_rejected": 0, "accepted": 0}

    def scan_target(self, name: str, target: mpf) -> List[FullCandidate]:
        candidates: List[FullCandidate] = []
        checked = 0
        t0 = time.time()
        hb = max(1, self.total // 10)
        self.stats = {"fast_rejected": 0, "stability_rejected": 0, "tol_rejected": 0,
                      "tail_rejected": 0, "cross_rejected": 0, "accepted": 0}

        P(f"--- SCANNING: {name} = {mp.nstr(target, 20)} ---")

        for a_poly in self.poly_space:
            for b_poly in self.poly_space:
                checked += 1

                if checked % hb == 0:
                    dt = time.time() - t0
                    rate = checked / dt if dt > 0 else 0
                    P(f"  [HB] {checked:,}/{self.total:,} | {rate:,.0f}/s | cands={len(candidates)}")

                # FAST FILTER (cheap, not evidence)
                try:
                    vf = eval_gcf(a_poly, b_poly, FAST_DEPTH)
                    if mp.isnan(vf) or mp.isinf(vf) or abs(vf - target) > FAST_BALLPARK:
                        self.stats["fast_rejected"] += 1
                        continue
                except Exception:
                    self.stats["fast_rejected"] += 1
                    continue

                # GATE A: Multi-depth stability
                result = gate_multidepth(a_poly, b_poly)
                if result is None:
                    self.stats["stability_rejected"] += 1
                    continue

                value, vals, deltas = result
                abs_err = abs(value - target)

                if abs_err > CANDIDATE_TOL:
                    self.stats["tol_rejected"] += 1
                    continue

                rel_err = abs_err / abs(target) if target != 0 else abs_err

                # GATE B: Tail sensitivity
                tail_ok, tail_m = gate_tail_sensitivity(a_poly, b_poly, value)
                if not tail_ok:
                    self.stats["tail_rejected"] += 1
                    # Still record but mark as REJECTED
                    pass

                # GATE C: Cross-check
                cross_ok, cross_m = gate_cross_check(a_poly, b_poly, target)
                if not cross_ok:
                    self.stats["cross_rejected"] += 1

                # Determine verdict
                all_pass = tail_ok and cross_ok
                verdict = "CANDIDATE" if all_pass else "REJECTED"
                discard = ""
                if not tail_ok:
                    discard += "Tail sensitivity FAIL (delta={}).".format(mp.nstr(tail_m, 8))
                if not cross_ok:
                    discard += " Cross-check FAIL (ratio={}).".format(mp.nstr(cross_m, 8))
                if all_pass:
                    discard = "Invalidate if higher-depth eval diverges or tail sensitivity fails at depth>320."
                    self.stats["accepted"] += 1

                c = FullCandidate(
                    target_name=name,
                    target_value=mp.nstr(target, 30),
                    a_poly=a_poly,
                    b_poly=b_poly,
                    a_str=poly_to_str(a_poly),
                    b_str=poly_to_str(b_poly),
                    approximation=mp.nstr(value, 30),
                    depths=list(DEPTHS),
                    values=[mp.nstr(v, 25) for v in vals],
                    deltas=[mp.nstr(d, 10) for d in deltas],
                    stability_score=mp.nstr(max(deltas) if deltas else 0, 10),
                    abs_error=mp.nstr(abs_err, 15),
                    rel_error=mp.nstr(rel_err, 15),
                    tail_pass=tail_ok,
                    tail_metric=mp.nstr(tail_m, 10),
                    cross_pass=cross_ok,
                    cross_metric=mp.nstr(cross_m, 8),
                    verdict=verdict,
                    discard_condition=discard,
                )
                candidates.append(c)

                if len(candidates) >= TOP_K:
                    break
            if len(candidates) >= TOP_K:
                break

        dt = time.time() - t0
        P(f"  [DONE] {checked:,} pairs in {dt:.1f}s | {len(candidates)} candidates found")
        P(f"  [STATS] fast_rej={self.stats['fast_rejected']:,} stab_rej={self.stats['stability_rejected']:,} "
          f"tol_rej={self.stats['tol_rejected']:,} tail_rej={self.stats['tail_rejected']:,} "
          f"cross_rej={self.stats['cross_rejected']:,} accepted={self.stats['accepted']}")

        # Rank by abs error (only accepted first, then rejected)
        accepted = [c for c in candidates if c.verdict == "CANDIDATE"]
        rejected = [c for c in candidates if c.verdict == "REJECTED"]
        accepted.sort(key=lambda c: mp.mpf(c.abs_error))
        rejected.sort(key=lambda c: mp.mpf(c.abs_error))
        ranked = accepted + rejected
        for i, c in enumerate(ranked):
            c.rank = i + 1
        return ranked


# ========================== REPORT ==========================
def print_step0():
    P("")
    P("=" * 80)
    P("STEP 0 -- SPEC")
    P("=" * 80)
    P(f"Structure class: Generalized Continued Fraction (GCF)")
    P(f"  a(n), b(n) are polynomials of degree <= {MAX_DEGREE}")
    P(f"  Coefficient range: {list(COEFF_RANGE)}")
    P(f"  Depth schedule: {DEPTHS}")
    P(f"  Precision: {PRECISION_DPS} decimal digits (mpmath)")
    P(f"Targets: pi, e, 4/pi, 1/pi (calibration) + gamma (exploratory)")
    P("")


def print_step1():
    P("=" * 80)
    P("STEP 1 -- FAILURE MODES CHECKLIST")
    P("=" * 80)
    P("  [x] Finite depth coincidence        -> multi-depth gate (N,2N,4N,8N)")
    P("  [x] Numerical rounding artifacts    -> mpmath at 30 dps")
    P("  [x] Divergent/oscillatory sequences -> delta-decreasing check")
    P("  [x] Tail dependency / truncation    -> tail sensitivity gate (perturb last 5 terms)")
    P("  [x] Ballpark filter bias            -> filter stats tracked; not treated as evidence")
    P("")


def print_step2():
    P("=" * 80)
    P("STEP 2 -- TEST PLAN")
    P("=" * 80)
    P(f"  A) Multi-depth: depths={DEPTHS}, deltas must decrease, max < {STABILITY_EPS}")
    P(f"  B) Tail sensitivity: perturb last {TAIL_K} a(n) by {TAIL_PERTURB}, delta < {TAIL_THRESHOLD}")
    P(f"  C) Cross-check: |v - target| / |v - (target+/-{CROSS_EPS})| > 5")
    P(f"  D) Calibration: run on phi, pi, e first to validate engine")
    P("")


def print_step4(all_candidates: Dict[str, List[FullCandidate]], timings: Dict[str, float]):
    P("")
    P("=" * 80)
    P("STEP 4 -- OUTPUT CONTRACT (per-candidate reports)")
    P("=" * 80)
    P("")

    total_accepted = 0
    total_found = 0

    for name, cands in all_candidates.items():
        if not cands:
            P(f"TARGET: {name}")
            P("-" * 50)
            P("NO STRUCTURAL CANDIDATES FOUND UNDER CURRENT CONSTRAINTS")
            P("")
            continue

        for c in cands:
            total_found += 1
            if c.verdict == "CANDIDATE":
                total_accepted += 1

            P(f"STRUCTURAL CANDIDATE #{c.rank}")
            P("-" * 50)
            P(f"Target:             {c.target_name}")
            P(f"Target value:       {c.target_value}")
            P(f"Model:              GCF poly degree <= {MAX_DEGREE}")
            P(f"a(n):               {c.a_poly}  ->  {c.a_str}")
            P(f"b(n):               {c.b_poly}  ->  {c.b_str}")
            P(f"Depths:             {c.depths}")
            P(f"Values:             {c.values}")
            P(f"Stability deltas:   {c.deltas}")
            P(f"Stability score:    {c.stability_score}")
            P(f"Abs error (max d):  {c.abs_error}")
            P(f"Rel error (max d):  {c.rel_error}")
            P(f"Tail sensitivity:   {'PASS' if c.tail_pass else 'FAIL'}  (metric={c.tail_metric})")
            P(f"Cross-check:        {'PASS' if c.cross_pass else 'FAIL'}  (ratio={c.cross_metric})")
            t = timings.get(c.target_name, 0)
            P(f"Compute budget:     {t:.1f}s")
            P(f"VERDICT:            {c.verdict}")
            P(f"DISCARD CONDITION:  {c.discard_condition}")
            P("")

    return total_found, total_accepted


def print_step5(total_found: int, total_accepted: int, targets_count: int):
    P("=" * 80)
    P("STEP 5 -- NO HYPE CLOSURE")
    P("=" * 80)
    P(f"Scanned {targets_count} targets using GCF poly scanner (degree <= {MAX_DEGREE}).")
    P(f"Found {total_found} candidate(s), of which {total_accepted} passed all gates.")
    if total_accepted == 0:
        P("NO STRUCTURAL CANDIDATES FOUND under current constraints.")
    else:
        P(f"{total_accepted} candidate(s) survive as NUMERICAL COINCIDENCES for human review.")
    P("Results are NOT proofs, identities, or discoveries.")
    P("Numerical stability does not imply irrationality/rationality or closed form.")
    P("")


# ========================== MAIN ==========================
def main():
    P("")
    P("+" + "=" * 64 + "+")
    P("|  ANTIGRAVITY -- STRUCTURAL NUMERIC SEARCH v2.0 (Logic Harness) |")
    P("|  Engine: GCF Polynomial Scanner                                |")
    P("|  System: GAHENAX / Antigravity Core                            |")
    P("+" + "=" * 64 + "+")
    P("")

    # STEP 0
    print_step0()

    # STEP 1
    print_step1()

    # STEP 2
    print_step2()

    # STEP 3 -- SEARCH
    P("=" * 80)
    P("STEP 3 -- SEARCH EXECUTION")
    P("=" * 80)

    scanner = LogicHarnessScanner()
    P(f"[INIT] Poly candidates: {len(scanner.poly_space)}")
    P(f"[INIT] Total (a,b) pairs: {scanner.total:,}")
    P("")

    # STEP 2D -- Calibration first
    P("--- CALIBRATION PHASE ---")
    calibration_targets: Dict[str, mpf] = {
        "phi (calibration)": mp.phi,
        "pi (calibration)": mp.pi,
        "e (calibration)": mp.e,
    }

    all_candidates: Dict[str, List[FullCandidate]] = {}
    timings: Dict[str, float] = {}

    for name, val in calibration_targets.items():
        t0 = time.time()
        cands = scanner.scan_target(name, val)
        timings[name] = time.time() - t0
        all_candidates[name] = cands
        P("")

    P("--- EXPLORATION PHASE ---")
    exploration_targets: Dict[str, mpf] = {
        "4/pi": 4 / mp.pi,
        "1/pi": 1 / mp.pi,
        "gamma (Euler-Mascheroni)": mp.euler,
    }

    for name, val in exploration_targets.items():
        t0 = time.time()
        cands = scanner.scan_target(name, val)
        timings[name] = time.time() - t0
        all_candidates[name] = cands
        P("")

    # STEP 4 -- Report
    total_found, total_accepted = print_step4(all_candidates, timings)

    # STEP 5 -- No Hype Closure
    print_step5(total_found, total_accepted, len(all_candidates))

    # Save JSON
    data = {}
    for name, cands in all_candidates.items():
        data[name] = []
        for c in cands:
            data[name].append({
                "target_name": c.target_name,
                "target_value": c.target_value,
                "a_poly": list(c.a_poly),
                "b_poly": list(c.b_poly),
                "a_str": c.a_str,
                "b_str": c.b_str,
                "approximation": c.approximation,
                "depths": c.depths,
                "values": c.values,
                "deltas": c.deltas,
                "stability_score": c.stability_score,
                "abs_error": c.abs_error,
                "rel_error": c.rel_error,
                "tail_pass": c.tail_pass,
                "tail_metric": c.tail_metric,
                "cross_pass": c.cross_pass,
                "cross_metric": c.cross_metric,
                "verdict": c.verdict,
                "discard_condition": c.discard_condition,
                "rank": c.rank,
            })
    with open("core/structural_search_results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    P("[SAVED] core/structural_search_results.json")

    P("")
    P("DISCLAIMER: All results are NUMERICAL COINCIDENCES identified via")
    P("finite-depth evaluation. They are NOT proofs, identities, or resolutions")
    P("of open problems. They are STRUCTURAL CANDIDATES for review by a")
    P("human mathematician.")
    P("")


if __name__ == "__main__":
    main()
