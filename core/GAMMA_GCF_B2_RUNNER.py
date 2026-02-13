#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GAMMA_GCF_B2_RUNNER.py
======================
Implements GAMMA_GCF_B2_v1: Gap-first, Anti-Cluster, Futility Stop.

Pipeline:
  STAGE 0 -- Ultra-cheap gap filter (depth 16, gap <= 1e-6)
  STAGE 1 -- Confirmed gap (depth 64/128, gap <= 1e-10)
  STAGE 2 -- Hard stability (multi-precision, depth 128/256)

Anti-cluster: bucket by converged value, max M=3 per bucket.
Futility stop: 5 consecutive windows of 50k with no 100x gap improvement.

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

# ========================== CONFIGURATION ==========================
# Stage 0 (ultra-cheap)
N0 = 16
PREC0_DPS = 24   # ~80 bits
G0 = mp.mpf("1e-6")

# Stage 1 (gap confirmation)
N1 = 64
N2 = 128
G1 = mp.mpf("1e-10")

# Stage 2 (hard stability)
N2_DEEP = 128
N2_DEEPER = 256
PREC_LOW_DPS = 24   # ~80 bits
PREC_HIGH_DPS = 48  # ~160 bits
SMIN = 20

# Anti-cluster
BUCKET_DECIMALS = 8
BUCKET_MAX = 3

# Futility stop
WINDOW_SIZE = 50_000
FUTILITY_WINDOWS = 5
FUTILITY_FACTOR = 100  # must improve by 100x

# Search space
MAX_DEGREE = 3
COEFF_RANGE = range(-5, 6)

# Output
TOP_K = 25

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
    b0 = abs(q[-1]) if q else 0
    return sum(abs(c) for c in p) + sum(abs(c) for c in q) + 2*poly_degree(p) + 2*poly_degree(q) + b0


def poly_gcd_val(coeffs: Poly) -> int:
    nonzero = [abs(c) for c in coeffs if c != 0]
    if not nonzero:
        return 1
    return reduce(gcd, nonzero)


# ========================== CANONICALIZATION ==========================
def canonical_q(coeffs: Poly) -> Optional[Poly]:
    leading_idx = -1
    for i, c in enumerate(coeffs):
        if c != 0:
            leading_idx = i
            break
    if leading_idx == -1:
        return None
    if coeffs[leading_idx] < 0:
        coeffs = tuple(-c for c in coeffs)
    g = poly_gcd_val(coeffs)
    if g > 1:
        coeffs = tuple(c // g for c in coeffs)
    return coeffs


def canonical_p(coeffs: Poly) -> Optional[Poly]:
    if all(c == 0 for c in coeffs):
        return None
    g = poly_gcd_val(coeffs)
    if g > 1:
        coeffs = tuple(c // g for c in coeffs)
    return coeffs


def build_spaces(max_degree: int, coeff_range: range):
    length = max_degree + 1
    raw = list(itertools.product(coeff_range, repeat=length))
    p_set, q_set = set(), set()
    for poly in raw:
        cp = canonical_p(poly)
        if cp is not None:
            p_set.add(cp)
        cq = canonical_q(poly)
        if cq is not None:
            q_set.add(cq)
    # Sort by L1 norm (simplest first)
    return sorted(p_set, key=lambda x: sum(abs(c) for c in x)), \
           sorted(q_set, key=lambda x: sum(abs(c) for c in x))


# ========================== GCF ENGINE ==========================
def eval_gcf(a: Poly, b: Poly, depth: int, dps: int) -> mp.mpf:
    old = mp.mp.dps
    mp.mp.dps = dps
    try:
        cur = mp.mpf(0)
        for n in range(depth, 0, -1):
            bn = mp.mpf(eval_poly(n, b)) + cur
            if bn == 0:
                return mp.mpf("inf")
            cur = mp.mpf(eval_poly(n, a)) / bn
        return mp.mpf(eval_poly(0, b)) + cur
    finally:
        mp.mp.dps = old


# ========================== Q SINGULARITY PREFILTER ==========================
def q_is_safe(q: Poly) -> bool:
    for n in range(1, 21):
        if eval_poly(n, q) == 0:
            return False
    return True


# ========================== ANTI-CLUSTER BUCKETS ==========================
class AntiClusterBuckets:
    def __init__(self, decimals: int = BUCKET_DECIMALS, max_per: int = BUCKET_MAX):
        self.decimals = decimals
        self.max_per = max_per
        self.buckets: Dict[str, List[Tuple[float, dict]]] = {}
        self.discards = 0

    def bucket_key(self, value: float) -> str:
        return f"{value:.{self.decimals}f}"

    def try_insert(self, value: float, gap: float, entry: dict) -> bool:
        key = self.bucket_key(value)
        if key not in self.buckets:
            self.buckets[key] = [(gap, entry)]
            return True
        bucket = self.buckets[key]
        if len(bucket) < self.max_per:
            bucket.append((gap, entry))
            bucket.sort(key=lambda x: x[0])
            return True
        # Full bucket: check if this is better than worst
        if gap < bucket[-1][0]:
            bucket[-1] = (gap, entry)
            bucket.sort(key=lambda x: x[0])
            self.discards += 1
            return True
        else:
            self.discards += 1
            return False

    def all_entries(self) -> List[dict]:
        result = []
        for bucket in self.buckets.values():
            for _, entry in bucket:
                result.append(entry)
        return result


# ========================== FUTILITY MONITOR ==========================
class FutilityMonitor:
    def __init__(self, window: int = WINDOW_SIZE, max_stale: int = FUTILITY_WINDOWS,
                 factor: float = FUTILITY_FACTOR):
        self.window = window
        self.max_stale = max_stale
        self.factor = factor
        self.windows_best: List[float] = []
        self.current_best = float("inf")
        self.stale_count = 0
        self.triggered = False

    def update(self, gap: float):
        if gap < self.current_best:
            self.current_best = gap

    def end_window(self) -> bool:
        self.windows_best.append(self.current_best)
        if len(self.windows_best) >= 2:
            prev = self.windows_best[-2]
            curr = self.windows_best[-1]
            improved = prev / curr >= self.factor if curr > 0 else True
            if improved:
                self.stale_count = 0
            else:
                self.stale_count += 1
        if self.stale_count >= self.max_stale:
            self.triggered = True
            return True
        self.current_best = float("inf")  # reset for next window
        return False


# ========================== MAIN SCANNER ==========================
@dataclass
class Stats:
    total_checked: int = 0
    s0_pass: int = 0
    s0_fail: int = 0
    num_fail: int = 0
    s1_pass: int = 0
    s1_fail: int = 0
    s2_pass: int = 0
    s2_fail: int = 0
    cluster_discards: int = 0
    futility_triggered: bool = False
    futility_windows: int = 0
    windows_best: List[float] = field(default_factory=list)
    overall_best_gap: float = float("inf")


def run_b2_search(target: mp.mpf, time_limit: float = 900.0):
    P(f"\n{'='*80}")
    P(f"B2 SEARCH: gamma = {mp.nstr(target, 40)}")
    P(f"{'='*80}")

    p_space, q_space = build_spaces(MAX_DEGREE, COEFF_RANGE)
    # Pre-filter Q for singularities
    q_safe = [q for q in q_space if q_is_safe(q)]
    q_rejected = len(q_space) - len(q_safe)

    total_p, total_q = len(p_space), len(q_safe)
    total_pairs = total_p * total_q

    P(f"[INIT] P polys: {total_p} | Q polys: {total_q} (rejected {q_rejected} singular)")
    P(f"[INIT] Total pairs: {total_pairs:,}")
    P(f"[CONFIG] Stages: S0(N={N0},G0={G0}) -> S1(N={N1}/{N2},G1={G1}) -> S2(N={N2_DEEP}/{N2_DEEPER},Smin={SMIN})")
    P(f"[CONFIG] Anti-cluster: B={BUCKET_DECIMALS} decimals, M={BUCKET_MAX}/bucket")
    P(f"[CONFIG] Futility: W={WINDOW_SIZE}, {FUTILITY_WINDOWS} stale windows, {FUTILITY_FACTOR}x factor")
    P("")

    stats = Stats()
    buckets = AntiClusterBuckets()
    futility = FutilityMonitor()
    t0 = time.time()
    hb = max(1, total_pairs // 20)

    stop_reason = "COMPLETE"

    for q_poly in q_safe:
        for p_poly in p_space:
            stats.total_checked += 1

            if stats.total_checked % hb == 0:
                dt = time.time() - t0
                rate = stats.total_checked / dt if dt > 0 else 0
                P(f"  [HB] {stats.total_checked:,}/{total_pairs:,} | {rate:,.0f}/s | "
                  f"S0={stats.s0_pass} S1={stats.s1_pass} S2={stats.s2_pass} "
                  f"best_gap={stats.overall_best_gap:.2e}")

            # Time limit (backup)
            if time.time() - t0 > time_limit:
                stop_reason = "TIME_LIMIT"
                break

            # Futility window check
            if stats.total_checked % WINDOW_SIZE == 0 and stats.total_checked > 0:
                if futility.end_window():
                    stop_reason = "FUTILITY"
                    P(f"  [FUTILITY STOP] at {stats.total_checked:,}")
                    break

            # ==================== STAGE 0 ====================
            try:
                v0 = eval_gcf(p_poly, q_poly, N0, PREC0_DPS)
            except Exception:
                stats.num_fail += 1
                continue

            if mp.isnan(v0) or mp.isinf(v0):
                stats.num_fail += 1
                continue

            gap0 = float(abs(v0 - target))
            if gap0 > float(G0):
                stats.s0_fail += 1
                continue

            stats.s0_pass += 1

            # ==================== STAGE 1 ====================
            try:
                v1 = eval_gcf(p_poly, q_poly, N1, PREC0_DPS)
                v2 = eval_gcf(p_poly, q_poly, N2, PREC0_DPS)
            except Exception:
                stats.num_fail += 1
                continue

            if mp.isnan(v2) or mp.isinf(v2):
                stats.num_fail += 1
                continue

            gap2 = float(abs(v2 - target))
            futility.update(gap2)

            if gap2 > float(G1):
                stats.s1_fail += 1
                continue

            stats.s1_pass += 1

            if gap2 < stats.overall_best_gap:
                stats.overall_best_gap = gap2
                P(f"  *** NEW BEST GAP: {gap2:.4e} | a={poly_to_str(p_poly)} b={poly_to_str(q_poly)}")

            # ==================== STAGE 2 ====================
            try:
                v_128_high = eval_gcf(p_poly, q_poly, N2_DEEP, PREC_HIGH_DPS)
                v_256_high = eval_gcf(p_poly, q_poly, N2_DEEPER, PREC_HIGH_DPS)
                v_256_low = eval_gcf(p_poly, q_poly, N2_DEEPER, PREC_LOW_DPS)
            except Exception:
                stats.num_fail += 1
                continue

            if any(mp.isnan(v) or mp.isinf(v) for v in [v_128_high, v_256_high, v_256_low]):
                stats.num_fail += 1
                continue

            # Test A: Truncation
            delta_trunc = abs(v_256_high - v_128_high)
            if delta_trunc == 0:
                stab_trunc = 50.0
            else:
                stab_trunc = float(-mp.log10(delta_trunc + mp.mpf("1e-60")))

            # Test B: Precision agreement
            prec_delta = abs(v_256_high - v_256_low)
            if prec_delta == 0:
                agree_digits = 50
            else:
                agree_digits = max(0, int(float(-mp.log10(prec_delta + mp.mpf("1e-60")))))

            stability_score = min(stab_trunc, float(agree_digits))

            if stability_score < SMIN:
                stats.s2_fail += 1
                continue

            stats.s2_pass += 1

            gap_final = float(abs(v_256_high - target))
            cc = complexity_cost(p_poly, q_poly)

            entry = {
                "p_poly": list(p_poly),
                "q_poly": list(q_poly),
                "p_str": poly_to_str(p_poly),
                "q_str": poly_to_str(q_poly),
                "deg_p": poly_degree(p_poly),
                "deg_q": poly_degree(q_poly),
                "b0": q_poly[-1],
                "complexity_cost": cc,
                "v_128": mp.nstr(v_128_high, 35),
                "v_256": mp.nstr(v_256_high, 35),
                "gap2": f"{gap_final:.6e}",
                "delta_trunc": mp.nstr(delta_trunc, 10),
                "stab_trunc": round(stab_trunc, 2),
                "agree_digits": agree_digits,
                "stability_score": round(stability_score, 2),
                "gap_float": gap_final,
            }

            # Anti-cluster
            conv_val = float(v_256_high)
            inserted = buckets.try_insert(conv_val, gap_final, entry)
            if not inserted:
                stats.cluster_discards += 1

        if stop_reason != "COMPLETE":
            break

    elapsed = time.time() - t0
    stats.futility_triggered = futility.triggered
    stats.futility_windows = len(futility.windows_best)
    stats.windows_best = futility.windows_best
    stats.cluster_discards = buckets.discards

    P(f"\n  [DONE] {stats.total_checked:,} checked in {elapsed:.1f}s")
    P(f"  [STOP] {stop_reason}")

    # Collect all entries from buckets, sort by gap
    all_entries = buckets.all_entries()
    all_entries.sort(key=lambda e: (e["gap_float"], -e["stability_score"], e["complexity_cost"]))
    top_k = all_entries[:TOP_K]

    return stats, top_k, buckets, elapsed, stop_reason


# ========================== REPORT ==========================
def print_report(stats: Stats, top_k: List[dict], buckets: AntiClusterBuckets,
                 elapsed: float, stop_reason: str):
    P("")
    P("=" * 80)
    P("GAMMA GCF B2 -- FINAL REPORT")
    P("=" * 80)
    P(f"Target: gamma = {GAMMA_STR[:50]}...")
    P("")

    # Parameters
    P("PARAMETERS:")
    P(f"  N0={N0}, N1={N1}, N2={N2}, N2_deep={N2_DEEP}, N2_deeper={N2_DEEPER}")
    P(f"  prec_low={PREC_LOW_DPS}dps, prec_high={PREC_HIGH_DPS}dps")
    P(f"  G0={G0}, G1={G1}, Smin={SMIN}")
    P(f"  Anti-cluster: B={BUCKET_DECIMALS}, M={BUCKET_MAX}")
    P(f"  Futility: W={WINDOW_SIZE}, max_stale={FUTILITY_WINDOWS}, factor={FUTILITY_FACTOR}")
    P(f"  Degree <= {MAX_DEGREE}, coefficients {list(COEFF_RANGE)}")
    P("")

    # Stage counts
    P("PIPELINE COUNTS:")
    P(f"  Total checked:     {stats.total_checked:,}")
    P(f"  Num failures:      {stats.num_fail:,}")
    P(f"  Stage 0 pass:      {stats.s0_pass:,} (fail: {stats.s0_fail:,})")
    P(f"  Stage 1 pass:      {stats.s1_pass:,} (fail: {stats.s1_fail:,})")
    P(f"  Stage 2 pass:      {stats.s2_pass:,} (fail: {stats.s2_fail:,})")
    P(f"  Cluster discards:  {stats.cluster_discards}")
    P(f"  Stop reason:       {stop_reason}")
    P(f"  Elapsed:           {elapsed:.1f}s")
    P("")

    # Anti-cluster info
    P("ANTI-CLUSTER:")
    P(f"  Total buckets: {len(buckets.buckets)}")
    P(f"  Cluster discards: {buckets.discards}")
    if buckets.buckets:
        top_buckets = sorted(buckets.buckets.items(), key=lambda x: -len(x[1]))[:5]
        P(f"  Top buckets by occupancy:")
        for key, members in top_buckets:
            P(f"    [{key}]: {len(members)} entries, best gap={members[0][0]:.4e}")
    P("")

    # Futility info
    P("FUTILITY MONITOR:")
    P(f"  Windows completed: {stats.futility_windows}")
    P(f"  Triggered: {stats.futility_triggered}")
    if stats.windows_best:
        for i, bg in enumerate(stats.windows_best):
            P(f"    Window {i+1}: best_gap2 = {bg:.4e}")
    P("")

    # Top-K table
    P("=" * 80)
    P("TOP-K CANDIDATES")
    P("=" * 80)
    if not top_k:
        P("  (no candidates passed all gates)")
    else:
        for i, c in enumerate(top_k):
            label = "STRUCTURAL CANDIDATE" if c["gap_float"] <= 1e-20 and c["stability_score"] >= SMIN else "SUB-THRESHOLD"
            P(f"\n  {label} #{i+1}")
            P(f"    P(n): {c['p_poly']}  ->  {c['p_str']}  deg={c['deg_p']}")
            P(f"    Q(n): {c['q_poly']}  ->  {c['q_str']}  deg={c['deg_q']}")
            P(f"    b0={c['b0']}, ComplexityCost={c['complexity_cost']}")
            P(f"    v(128): {c['v_128']}")
            P(f"    v(256): {c['v_256']}")
            P(f"    gap2:           {c['gap2']}")
            P(f"    delta_trunc:    {c['delta_trunc']}")
            P(f"    stab_trunc:     {c['stab_trunc']:.1f}")
            P(f"    agree_digits:   {c['agree_digits']}")
            P(f"    StabilityScore: {c['stability_score']:.1f}")
    P("")

    # Decision
    P("=" * 80)
    P("DECISION")
    P("=" * 80)
    if top_k and top_k[0]["gap_float"] <= 1e-20 and top_k[0]["stability_score"] >= SMIN:
        P(f"gamma: SIG_CANDIDATE")
        P(f"  min gap2 = {top_k[0]['gap2']}")
        P(f"  StabilityScore = {top_k[0]['stability_score']:.1f}")
        P("WARNING: This is NOT proof of a closed form.")
    else:
        P("gamma: NO_SIG")
        best_gap = top_k[0]["gap_float"] if top_k else stats.overall_best_gap
        best_stab = max((c["stability_score"] for c in top_k), default=0)
        P(f"  best_gap2 = {best_gap:.4e}")
        P(f"  best_stability = {best_stab:.1f}")
        if stats.futility_triggered:
            P(f"  FUTILITY evidence: {stats.futility_windows} windows, no 100x improvement")
        P(f"  No candidates with gap <= 1e-20 AND StabilityScore >= {SMIN}")
    P("")
    P("DISCLAIMER: All results are NUMERICAL COINCIDENCES. NOT proofs.")
    P("Numerical stability does not imply irrationality/rationality or closed form.")
    P("")


# ========================== MAIN ==========================
def main():
    P("")
    P("+" + "=" * 68 + "+")
    P("|  ANTIGRAVITY -- GAMMA GCF B2 (Gap-first, Anti-Cluster, Futility)  |")
    P("|  Engine: GCF Polynomial Scanner v5                                |")
    P("|  System: GAHENAX / Antigravity Core                               |")
    P("+" + "=" * 68 + "+")
    P("")

    mp.mp.dps = 60
    gamma = mp.mpf(GAMMA_STR)
    P(f"Target: gamma = {mp.nstr(gamma, 50)}")
    P(f"Source: hardcoded {len(GAMMA_STR)}-digit string")
    P(f"mpmath: v{mp.__version__}, dps={mp.mp.dps}")
    P("")

    stats, top_k, buckets, elapsed, stop_reason = run_b2_search(gamma, time_limit=600.0)

    print_report(stats, top_k, buckets, elapsed, stop_reason)

    # Save JSON
    data = {
        "target": "gamma (Euler-Mascheroni)",
        "target_value": GAMMA_STR,
        "parameters": {
            "N0": N0, "N1": N1, "N2": N2, "N2_deep": N2_DEEP, "N2_deeper": N2_DEEPER,
            "G0": str(G0), "G1": str(G1), "Smin": SMIN,
            "bucket_decimals": BUCKET_DECIMALS, "bucket_max": BUCKET_MAX,
            "window_size": WINDOW_SIZE, "futility_windows": FUTILITY_WINDOWS,
            "max_degree": MAX_DEGREE, "coeff_range": list(COEFF_RANGE),
        },
        "stats": {
            "total_checked": stats.total_checked,
            "num_fail": stats.num_fail,
            "s0_pass": stats.s0_pass, "s0_fail": stats.s0_fail,
            "s1_pass": stats.s1_pass, "s1_fail": stats.s1_fail,
            "s2_pass": stats.s2_pass, "s2_fail": stats.s2_fail,
            "cluster_discards": stats.cluster_discards,
            "futility_triggered": stats.futility_triggered,
            "windows_best": stats.windows_best,
            "overall_best_gap": stats.overall_best_gap,
            "stop_reason": stop_reason,
            "elapsed": elapsed,
        },
        "anti_cluster": {
            "total_buckets": len(buckets.buckets),
            "discards": buckets.discards,
        },
        "top_k": [{k: v for k, v in c.items() if k != "gap_float"} for c in top_k],
    }
    with open("core/gamma_b2_results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    P("[SAVED] core/gamma_b2_results.json")
    P("")


if __name__ == "__main__":
    main()
