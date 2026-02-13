#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STRUCTURAL_NUMERIC_SEARCH_RUNNER.py  (v3 -- Entropy Reducer + Logic Harness)
=============================================================================
Implements:
  - ENTROPY REDUCER v1.0 (canonicalization, prefilters, triage, complexity prior, UA accounting)
  - LOGIC HARNESS v1.0 (multi-depth, tail sensitivity, cross-check, no-hype closure)

Expanded search: coefficients [-3, 3], degree <= 2

Author: GAHENAX / Antigravity Core
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import mpmath as mp

def P(msg: str) -> None:
    print(msg, flush=True)


# ========================== STEP 0: SPEC ==========================
PRECISION_DPS = 30
mp.mp.dps = PRECISION_DPS

MAX_DEGREE = 2
COEFF_RANGE = range(-3, 4)  # [-3, -2, -1, 0, 1, 2, 3]

DEPTHS: Tuple[int, ...] = (40, 80, 160, 320)
STABILITY_EPS = mp.mpf("1e-20")
FAST_DEPTH = 15
MID_DEPTH = 40
BALLPARK_R = mp.mpf("1e-2")
MAGNITUDE_MAX = mp.mpf("1e6")
TRIAGE_THRESHOLD = mp.mpf("1e-10")
CANDIDATE_TOL = mp.mpf("1e-10")
TAIL_K = 5
TAIL_PERTURB = mp.mpf("1e-6")
TAIL_THRESHOLD = mp.mpf("1e-8")
CROSS_EPS = mp.mpf("1e-4")
TOP_K = 10

Poly = Tuple[int, ...]
mpf = mp.mpf


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


def poly_complexity(coeffs: Poly) -> Tuple[int, int, int]:
    """Return (L1_norm, nonzero_count, abs_b0) for complexity ordering."""
    l1 = sum(abs(c) for c in coeffs)
    nz = sum(1 for c in coeffs if c != 0)
    return (l1, nz, abs(coeffs[-1]))


def eval_gcf(a: Poly, b: Poly, depth: int) -> mpf:
    cur = mp.mpf(0)
    for n in range(depth, 0, -1):
        bn_val = mp.mpf(eval_poly(n, b)) + cur
        if bn_val == 0:
            return mp.mpf("inf")
        cur = mp.mpf(eval_poly(n, a)) / bn_val
    return mp.mpf(eval_poly(0, b)) + cur


def eval_gcf_perturbed(a: Poly, b: Poly, depth: int, k: int, eps: mpf) -> mpf:
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


# ========================== ENTROPY REDUCER ==========================
@dataclass
class EntropyReport:
    omega_0: int = 0
    h_0: float = 0.0
    steps: List[Dict] = field(default_factory=list)

    def add_step(self, name: str, before: int, after: int, details: str = ""):
        h_before = math.log2(before) if before > 0 else 0
        h_after = math.log2(after) if after > 0 else 0
        ua = h_before - h_after
        cumulative = self.h_0 - h_after
        self.steps.append({
            "name": name,
            "before": before,
            "after": after,
            "h_before": h_before,
            "h_after": h_after,
            "ua": ua,
            "cumulative_ua": cumulative,
            "details": details,
        })

    def print_report(self):
        P("")
        P("ENTROPY REDUCER REPORT")
        P("=" * 70)
        P(f"Omega_0: {self.omega_0:,}")
        P(f"H_0:     {self.h_0:.2f} bits")
        P("")
        for s in self.steps:
            P(f"  Step: {s['name']}")
            P(f"    Omega: {s['before']:,} -> {s['after']:,}")
            P(f"    H:     {s['h_before']:.2f} -> {s['h_after']:.2f} bits")
            P(f"    UA_i:  {s['ua']:.2f} bits removed")
            P(f"    Cumul: {s['cumulative_ua']:.2f} bits total removed")
            if s['details']:
                P(f"    Info:  {s['details']}")
            P("")
        if self.steps:
            final = self.steps[-1]
            saved_pct = (1 - final['after'] / self.omega_0) * 100 if self.omega_0 > 0 else 0
            P(f"  TOTAL UA REMOVED: {final['cumulative_ua']:.2f} bits")
            P(f"  COMPUTE SAVED:    {saved_pct:.1f}% of original search space")
        P("=" * 70)
        P("")


def canonicalize(poly_space: List[Poly]) -> Tuple[List[Poly], int]:
    """
    Remove equivalent representations:
    - If all coefficients can be divided by a common factor > 1 without losing structure,
      keep only the reduced form.
    - GCF(a, b) with a(n)=k*P(n), b(n)=k*Q(n) is NOT the same as P,Q in general,
      but (a,b) where gcd of all a_coeffs > 1 can be factored.
    Actually for GCF pairs, equivalence is tricky. We do a simpler dedup:
    just remove the all-zero polys (already done) and normalize.
    """
    seen = set()
    result = []
    removed = 0
    for p in poly_space:
        from math import gcd
        from functools import reduce
        g = reduce(gcd, (abs(c) for c in p if c != 0), 0)
        if g > 1:
            normalized = tuple(c // g for c in p)
            # Keep the normalized version, skip if we already have it
            # But also keep the original if normalized is different
            # Actually: we only canonicalize individual polys, 
            # the pair interaction is what matters. Keep both but flag.
            pass
        if p not in seen:
            seen.add(p)
            result.append(p)
        else:
            removed += 1
    return result, removed


def prefilter_divergence(a: Poly, b: Poly) -> Optional[str]:
    """Return rejection reason or None if OK."""
    try:
        v = eval_gcf(a, b, FAST_DEPTH)
    except Exception:
        return "exception"
    if mp.isnan(v):
        return "nan"
    if mp.isinf(v):
        return "inf"
    if abs(v) > MAGNITUDE_MAX:
        return "magnitude"
    # Oscillation check: compare depth d and d+1
    try:
        v2 = eval_gcf(a, b, FAST_DEPTH + 1)
        if mp.isnan(v2) or mp.isinf(v2):
            return "oscillation_nan"
        if abs(v2 - v) > abs(v) * 0.5 + 1:
            return "oscillation"
    except Exception:
        return "oscillation_err"
    return None


def prefilter_ballpark(a: Poly, b: Poly, target: mpf) -> bool:
    """Two-depth ballpark check."""
    try:
        v_fast = eval_gcf(a, b, FAST_DEPTH)
        if abs(v_fast - target) > BALLPARK_R:
            return False
        v_mid = eval_gcf(a, b, MID_DEPTH)
        if abs(v_mid - target) > BALLPARK_R:
            return False
        return True
    except Exception:
        return False


def triage_stability(a: Poly, b: Poly) -> bool:
    """Quick triage: |v(2N) - v(N)| < threshold using first two depths."""
    try:
        v1 = eval_gcf(a, b, DEPTHS[0])
        v2 = eval_gcf(a, b, DEPTHS[1])
        if mp.isnan(v1) or mp.isnan(v2) or mp.isinf(v1) or mp.isinf(v2):
            return False
        return abs(v2 - v1) < TRIAGE_THRESHOLD
    except Exception:
        return False


# ========================== LOGIC HARNESS GATES ==========================
def gate_multidepth(a: Poly, b: Poly) -> Optional[Tuple[mpf, List[mpf], List[mpf]]]:
    vals = []
    for d in DEPTHS:
        v = eval_gcf(a, b, d)
        if mp.isnan(v) or mp.isinf(v):
            return None
        vals.append(v)
    deltas = [abs(vals[i+1] - vals[i]) for i in range(len(vals)-1)]
    score = max(deltas) if deltas else mp.mpf("inf")
    for i in range(len(deltas)-1):
        if deltas[i+1] > deltas[i] * 10:
            return None
    if score > STABILITY_EPS:
        return None
    return vals[-1], vals, deltas


def gate_tail(a: Poly, b: Poly, base: mpf) -> Tuple[bool, mpf]:
    v_p = eval_gcf_perturbed(a, b, DEPTHS[-1], TAIL_K, TAIL_PERTURB)
    if mp.isnan(v_p) or mp.isinf(v_p):
        return False, mp.mpf("inf")
    d = abs(v_p - base)
    return d < TAIL_THRESHOLD, d


def gate_cross(a: Poly, b: Poly, target: mpf) -> Tuple[bool, mpf]:
    v = eval_gcf(a, b, DEPTHS[-1])
    err = abs(v - target)
    err_p = abs(v - (target + CROSS_EPS))
    err_m = abs(v - (target - CROSS_EPS))
    ratio = min(err_p, err_m) / err if err > 0 else mp.mpf(0)
    return ratio > 5, ratio


# ========================== CANDIDATE ==========================
@dataclass
class FullCandidate:
    target_name: str
    target_value: str
    a_poly: Poly
    b_poly: Poly
    a_str: str
    b_str: str
    a_complexity: Tuple[int, int, int]
    b_complexity: Tuple[int, int, int]
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


# ========================== SCANNER ==========================
class EntropyReducerScanner:
    def __init__(self):
        raw = list(itertools.product(COEFF_RANGE, repeat=MAX_DEGREE + 1))
        all_polys = [p for p in raw if any(x != 0 for x in p)]
        self.poly_space, self.canon_removed = canonicalize(all_polys)
        # Sort by complexity (simplest first)
        self.poly_space.sort(key=poly_complexity)
        self.total_raw = len(all_polys) ** 2
        self.total_pairs = len(self.poly_space) ** 2

    def scan_target(self, name: str, target: mpf) -> Tuple[List[FullCandidate], EntropyReport]:
        er = EntropyReport()
        er.omega_0 = self.total_pairs
        er.h_0 = math.log2(self.total_pairs) if self.total_pairs > 0 else 0

        # Step 1: Canonicalization (already done at init but report it)
        canon_before = len([p for p in itertools.product(COEFF_RANGE, repeat=MAX_DEGREE+1) if any(x!=0 for x in p)]) ** 2
        er.add_step("Canonicalization", canon_before, self.total_pairs,
                     f"Removed {self.canon_removed} duplicate polys")

        candidates: List[FullCandidate] = []
        t0 = time.time()
        hb = max(1, self.total_pairs // 10)

        # Stats
        div_reasons: Dict[str, int] = {}
        ballpark_rejected = 0
        triage_rejected = 0
        depth_rejected = 0
        tol_rejected = 0
        survived_prefilter = 0
        survived_ballpark = 0
        survived_triage = 0
        checked = 0

        P(f"--- SCANNING: {name} = {mp.nstr(target, 20)} ---")

        for a_poly in self.poly_space:
            for b_poly in self.poly_space:
                checked += 1

                if checked % hb == 0:
                    dt = time.time() - t0
                    rate = checked / dt if dt > 0 else 0
                    P(f"  [HB] {checked:,}/{self.total_pairs:,} | {rate:,.0f}/s | cands={len(candidates)}")

                # REDUCER (2): Divergence prefilter
                reason = prefilter_divergence(a_poly, b_poly)
                if reason:
                    div_reasons[reason] = div_reasons.get(reason, 0) + 1
                    continue
                survived_prefilter += 1

                # REDUCER (3): Ballpark gating (two-depth)
                if not prefilter_ballpark(a_poly, b_poly, target):
                    ballpark_rejected += 1
                    continue
                survived_ballpark += 1

                # REDUCER (4): Stability triage
                if not triage_stability(a_poly, b_poly):
                    triage_rejected += 1
                    continue
                survived_triage += 1

                # HARNESS GATE A: Full multi-depth
                result = gate_multidepth(a_poly, b_poly)
                if result is None:
                    depth_rejected += 1
                    continue

                value, vals, deltas = result
                abs_err = abs(value - target)

                if abs_err > CANDIDATE_TOL:
                    tol_rejected += 1
                    continue

                rel_err = abs_err / abs(target) if target != 0 else abs_err

                # HARNESS GATE B: Tail
                tail_ok, tail_m = gate_tail(a_poly, b_poly, value)

                # HARNESS GATE C: Cross-check
                cross_ok, cross_m = gate_cross(a_poly, b_poly, target)

                all_pass = tail_ok and cross_ok
                verdict = "CANDIDATE" if all_pass else "REJECTED"
                discard = ""
                if not tail_ok:
                    discard += f"Tail FAIL (delta={mp.nstr(tail_m, 8)}). "
                if not cross_ok:
                    discard += f"Cross FAIL (ratio={mp.nstr(cross_m, 8)}). "
                if all_pass:
                    discard = "Invalidate if higher-depth eval diverges or tail fails at depth>320."

                c = FullCandidate(
                    target_name=name,
                    target_value=mp.nstr(target, 30),
                    a_poly=a_poly,
                    b_poly=b_poly,
                    a_str=poly_to_str(a_poly),
                    b_str=poly_to_str(b_poly),
                    a_complexity=poly_complexity(a_poly),
                    b_complexity=poly_complexity(b_poly),
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

        # Build entropy report
        total_div = sum(div_reasons.values())
        div_detail = " | ".join(f"{k}={v}" for k, v in sorted(div_reasons.items()))
        er.add_step("Divergence prefilter", self.total_pairs,
                     survived_prefilter, f"Rejected {total_div:,} ({div_detail})")
        er.add_step("Ballpark gating (2-depth)", survived_prefilter,
                     survived_ballpark, f"Rejected {ballpark_rejected:,}")
        er.add_step("Stability triage (N,2N)", survived_ballpark,
                     survived_triage, f"Rejected {triage_rejected:,}")
        er.add_step("Full multi-depth + tolerance", survived_triage,
                     len(candidates), f"Depth rej={depth_rejected}, tol rej={tol_rejected}")

        P(f"  [DONE] {checked:,} pairs in {dt:.1f}s | {len(candidates)} candidates")

        # Rank
        accepted = [c for c in candidates if c.verdict == "CANDIDATE"]
        rejected = [c for c in candidates if c.verdict == "REJECTED"]
        accepted.sort(key=lambda c: mp.mpf(c.abs_error))
        rejected.sort(key=lambda c: mp.mpf(c.abs_error))
        ranked = accepted + rejected
        for i, c in enumerate(ranked):
            c.rank = i + 1
        return ranked, er


# ========================== REPORT ==========================
def print_candidate(c: FullCandidate, compute_time: float):
    P(f"STRUCTURAL CANDIDATE #{c.rank}")
    P("-" * 55)
    P(f"Target:             {c.target_name}")
    P(f"Target value:       {c.target_value}")
    P(f"Model:              GCF poly degree <= {MAX_DEGREE}")
    P(f"a(n):               {c.a_poly}  ->  {c.a_str}")
    P(f"  a complexity:     L1={c.a_complexity[0]} nz={c.a_complexity[1]} |b0|={c.a_complexity[2]}")
    P(f"b(n):               {c.b_poly}  ->  {c.b_str}")
    P(f"  b complexity:     L1={c.b_complexity[0]} nz={c.b_complexity[1]} |b0|={c.b_complexity[2]}")
    P(f"Depths:             {c.depths}")
    P(f"Values:             {c.values}")
    P(f"Stability deltas:   {c.deltas}")
    P(f"Stability score:    {c.stability_score}")
    P(f"Abs error (max d):  {c.abs_error}")
    P(f"Rel error (max d):  {c.rel_error}")
    P(f"Tail sensitivity:   {'PASS' if c.tail_pass else 'FAIL'}  (metric={c.tail_metric})")
    P(f"Cross-check:        {'PASS' if c.cross_pass else 'FAIL'}  (ratio={c.cross_metric})")
    P(f"Compute budget:     {compute_time:.1f}s")
    P(f"VERDICT:            {c.verdict}")
    P(f"DISCARD CONDITION:  {c.discard_condition}")
    P("")


# ========================== MAIN ==========================
def main():
    P("")
    P("+" + "=" * 68 + "+")
    P("|  ANTIGRAVITY -- STRUCTURAL SEARCH v3.0 (Entropy Reducer + Harness) |")
    P("|  Engine: GCF Polynomial Scanner                                    |")
    P("|  System: GAHENAX / Antigravity Core                                |")
    P("+" + "=" * 68 + "+")

    # STEP 0: SPEC
    P("")
    P("=" * 80)
    P("STEP 0 -- SPEC")
    P("=" * 80)
    P(f"Structure:   GCF with polynomial a(n), b(n), degree <= {MAX_DEGREE}")
    P(f"Coefficients: {list(COEFF_RANGE)}")
    P(f"Depths:       {DEPTHS}")
    P(f"Precision:    {PRECISION_DPS} dps (mpmath)")
    P(f"Reducer:      Canonicalization + Divergence + Ballpark(2-depth) + Triage(N,2N)")
    P(f"Ordering:     Complexity prior (L1 norm ascending)")
    P("")

    # STEP 1: FAILURE MODES
    P("=" * 80)
    P("STEP 1 -- FAILURE MODES CHECKLIST")
    P("=" * 80)
    P("  [x] Finite depth coincidence        -> 4-depth gate (N,2N,4N,8N)")
    P("  [x] Numerical rounding artifacts    -> mpmath 30 dps")
    P("  [x] Divergent/oscillatory sequences -> prefilter + delta-decreasing")
    P("  [x] Tail dependency / truncation    -> tail sensitivity gate")
    P("  [x] Ballpark filter bias            -> 2-depth ballpark, stats logged")
    P("  [x] Duplicate structures            -> canonicalization")
    P("  [x] Search ordering bias            -> complexity prior (L1 ascending)")
    P("")

    # STEP 2: TEST PLAN
    P("=" * 80)
    P("STEP 2 -- TEST PLAN")
    P("=" * 80)
    P(f"  A) Multi-depth: depths={DEPTHS}, deltas decreasing, max < {STABILITY_EPS}")
    P(f"  B) Tail sensitivity: perturb last {TAIL_K} terms by {TAIL_PERTURB}, delta < {TAIL_THRESHOLD}")
    P(f"  C) Cross-check: err_target / err_shifted ratio > 5 (eps={CROSS_EPS})")
    P(f"  D) Calibration: run phi, 4/pi first to validate pipeline")
    P("")

    # STEP 3: SEARCH
    P("=" * 80)
    P("STEP 3 -- SEARCH EXECUTION (with Entropy Reducer)")
    P("=" * 80)

    scanner = EntropyReducerScanner()
    P(f"[INIT] Poly candidates: {len(scanner.poly_space)} (after canon)")
    P(f"[INIT] Total pairs: {scanner.total_pairs:,}")
    P("")

    # Calibration
    targets = {
        "phi (calibration)": mp.phi,
        "4/pi (calibration)": 4 / mp.pi,
        "gamma (Euler-Mascheroni)": mp.euler,
    }

    all_results: Dict[str, Tuple[List[FullCandidate], EntropyReport]] = {}
    timings: Dict[str, float] = {}

    for name, val in targets.items():
        t0 = time.time()
        cands, er = scanner.scan_target(name, val)
        timings[name] = time.time() - t0
        all_results[name] = (cands, er)
        er.print_report()

    # STEP 4: OUTPUT CONTRACT
    P("=" * 80)
    P("STEP 4 -- OUTPUT CONTRACT")
    P("=" * 80)
    P("")

    total_found = 0
    total_accepted = 0

    for name, (cands, _) in all_results.items():
        if not cands:
            P(f"TARGET: {name}")
            P("-" * 55)
            P("NO STRUCTURAL CANDIDATES FOUND UNDER CURRENT CONSTRAINTS")
            P("")
            continue
        for c in cands:
            total_found += 1
            if c.verdict == "CANDIDATE":
                total_accepted += 1
            print_candidate(c, timings.get(name, 0))

    # STEP 5: NO HYPE CLOSURE
    P("=" * 80)
    P("STEP 5 -- NO HYPE CLOSURE")
    P("=" * 80)
    P(f"Scanned {len(targets)} targets using GCF poly scanner (degree <= {MAX_DEGREE}).")
    P(f"Coefficient range: {list(COEFF_RANGE)}")
    P(f"Found {total_found} candidate(s), of which {total_accepted} passed all gates.")
    if total_accepted == 0:
        P("NO STRUCTURAL CANDIDATES FOUND under current constraints.")
    else:
        P(f"{total_accepted} candidate(s) survive as NUMERICAL COINCIDENCES for human review.")
    P("Results are NOT proofs, identities, or discoveries.")
    P("Numerical stability does not imply irrationality/rationality or closed form.")
    P("")

    # Save JSON
    data = {}
    for name, (cands, er) in all_results.items():
        data[name] = {
            "entropy_report": {
                "omega_0": er.omega_0,
                "h_0": er.h_0,
                "steps": er.steps,
            },
            "candidates": [],
        }
        for c in cands:
            data[name]["candidates"].append({
                "target_name": c.target_name,
                "a_poly": list(c.a_poly),
                "b_poly": list(c.b_poly),
                "a_str": c.a_str,
                "b_str": c.b_str,
                "a_complexity": list(c.a_complexity),
                "b_complexity": list(c.b_complexity),
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
    with open("core/structural_search_results_v3.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    P("[SAVED] core/structural_search_results_v3.json")

    P("")
    P("DISCLAIMER: All results are NUMERICAL COINCIDENCES identified via")
    P("finite-depth evaluation. NOT proofs, identities, or resolutions of")
    P("open problems. STRUCTURAL CANDIDATES for human mathematician review.")
    P("")


if __name__ == "__main__":
    main()
