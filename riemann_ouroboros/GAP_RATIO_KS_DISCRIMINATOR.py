#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GAP_RATIO_KS_DISCRIMINATOR.py
==============================
Gap Ratio Vector analysis: r_i = min(s_i, s_{i+1}) / max(s_i, s_{i+1})

Per-block features:
  - r_mean (mean gap ratio)
  - histogram (fixed bins)
  - entropy of histogram
  - KS distance to GUE control distribution
  - KS distance to Poisson control distribution

Decision: if KS(r, GUE) < KS(r, Poi) in > threshold% blocks -> "GUE alignment"

Author: GAHENAX Core
"""
from __future__ import annotations

import sys
import os
import json
import time
import argparse
import numpy as np
from scipy import stats
from typing import List, Dict, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from controls import gue_spacings, poisson_spacings

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ============================================================================
# GAP RATIO CORE
# ============================================================================

def compute_gap_ratios(spacings: np.ndarray) -> np.ndarray:
    """r_i = min(s_i, s_{i+1}) / max(s_i, s_{i+1})."""
    s = np.asarray(spacings, dtype=np.float64)
    s = s[np.isfinite(s) & (s > 0)]
    if len(s) < 3:
        return np.array([])
    s0 = s[:-1]
    s1 = s[1:]
    eps = 1e-30
    return np.minimum(s0, s1) / (np.maximum(s0, s1) + eps)


# ============================================================================
# HISTOGRAM + ENTROPY
# ============================================================================

HIST_BINS = np.linspace(0.0, 1.0, 51)  # 50 bins from 0 to 1


def gap_ratio_histogram(r: np.ndarray) -> np.ndarray:
    """Fixed-bin histogram of gap ratios (density-normalized)."""
    hist, _ = np.histogram(r, bins=HIST_BINS, density=True)
    return hist


def histogram_entropy(hist: np.ndarray) -> float:
    """Shannon entropy of a histogram (treated as probability distribution)."""
    p = hist / (hist.sum() + 1e-30)
    p = p[p > 0]
    return -float(np.sum(p * np.log(p)))


# ============================================================================
# REFERENCE DISTRIBUTIONS (build from many control blocks)
# ============================================================================

def build_reference_distribution(kind: str, n_blocks: int = 100,
                                  block_length: int = 4000,
                                  base_seed: int = 7000) -> np.ndarray:
    """
    Build a large reference gap-ratio sample from synthetic controls.
    Returns: concatenated gap ratios from n_blocks blocks.
    """
    all_r = []
    for i in range(n_blocks):
        seed = base_seed + i
        if kind.lower() == "gue":
            sp = gue_spacings(block_length, seed=seed)
        else:
            sp = poisson_spacings(block_length, seed=seed)
        r = compute_gap_ratios(sp)
        all_r.append(r)
    return np.concatenate(all_r)


# ============================================================================
# PER-BLOCK ANALYSIS
# ============================================================================

def analyze_block(spacings: np.ndarray,
                  ref_gue: np.ndarray,
                  ref_poi: np.ndarray) -> Dict[str, Any]:
    """
    Full gap-ratio analysis for one block.
    Returns features + KS distances + vote.
    """
    r = compute_gap_ratios(spacings)
    if len(r) < 20:
        return {"error": "too_few_ratios", "n_ratios": len(r)}

    r_mean = float(np.mean(r))
    r_std = float(np.std(r))
    r_median = float(np.median(r))

    hist = gap_ratio_histogram(r)
    entropy = histogram_entropy(hist)

    # KS 2-sample tests against reference distributions
    ks_gue = stats.ks_2samp(r, ref_gue)
    ks_poi = stats.ks_2samp(r, ref_poi)

    vote = "GUE" if ks_gue.statistic < ks_poi.statistic else "POISSON"

    return {
        "n_ratios": len(r),
        "r_mean": round(r_mean, 6),
        "r_std": round(r_std, 6),
        "r_median": round(r_median, 6),
        "entropy": round(entropy, 6),
        "ks_gue_stat": round(float(ks_gue.statistic), 6),
        "ks_gue_pval": round(float(ks_gue.pvalue), 6),
        "ks_poi_stat": round(float(ks_poi.statistic), 6),
        "ks_poi_pval": round(float(ks_poi.pvalue), 6),
        "ks_margin": round(float(ks_poi.statistic - ks_gue.statistic), 6),
        "vote": vote,
    }


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    ap = argparse.ArgumentParser(description="Gap Ratio KS Discriminator")
    ap.add_argument("--n_test_blocks", type=int, default=50,
                    help="Number of test blocks per type (GUE and Poisson)")
    ap.add_argument("--n_ref_blocks", type=int, default=100,
                    help="Number of reference blocks for building control distributions")
    ap.add_argument("--block_length", type=int, default=4000,
                    help="Spacings per block")
    ap.add_argument("--vote_threshold", type=float, default=0.80,
                    help="Min vote rate for alignment conclusion")
    ap.add_argument("--base_seed", type=int, default=42)
    args = ap.parse_args()

    print("", flush=True)
    print("+" + "=" * 68 + "+", flush=True)
    print("|  GAP RATIO KS DISCRIMINATOR                                      |", flush=True)
    print("|  r_i = min(s_i, s_{i+1}) / max(s_i, s_{i+1})                     |", flush=True)
    print("|  System: GAHENAX / Antigravity Core                               |", flush=True)
    print("+" + "=" * 68 + "+", flush=True)
    print("", flush=True)

    print(f"CONFIG:", flush=True)
    print(f"  test_blocks/type: {args.n_test_blocks}", flush=True)
    print(f"  ref_blocks:       {args.n_ref_blocks}", flush=True)
    print(f"  block_length:     {args.block_length}", flush=True)
    print(f"  vote_threshold:   {args.vote_threshold}", flush=True)
    print(f"  base_seed:        {args.base_seed}", flush=True)
    print("", flush=True)

    t0 = time.time()

    # === Build reference distributions ===
    print("[PHASE 1] Building reference distributions...", flush=True)
    ref_gue = build_reference_distribution(
        "gue", n_blocks=args.n_ref_blocks,
        block_length=args.block_length, base_seed=args.base_seed + 50000
    )
    ref_poi = build_reference_distribution(
        "poisson", n_blocks=args.n_ref_blocks,
        block_length=args.block_length, base_seed=args.base_seed + 60000
    )
    print(f"  GUE reference: {len(ref_gue)} ratios "
          f"(mean={np.mean(ref_gue):.4f})", flush=True)
    print(f"  Poisson reference: {len(ref_poi)} ratios "
          f"(mean={np.mean(ref_poi):.4f})", flush=True)
    print(f"  Expected: GUE ~0.5996, Poisson ~0.3863", flush=True)
    print("", flush=True)

    # === Generate and analyze test blocks ===
    print("[PHASE 2] Analyzing test blocks...", flush=True)

    all_results = []

    # GUE test blocks (separate seeds from reference)
    print(f"  Testing {args.n_test_blocks} GUE blocks...", flush=True)
    for i in range(args.n_test_blocks):
        seed = args.base_seed + 100000 + i
        sp = gue_spacings(args.block_length, seed=seed)
        result = analyze_block(sp, ref_gue, ref_poi)
        result["true_type"] = "gue"
        result["block_id"] = f"gue_test_{i:04d}"
        result["seed"] = seed
        all_results.append(result)
        if (i + 1) % 10 == 0:
            print(f"    gue {i+1}/{args.n_test_blocks}", flush=True)

    # Poisson test blocks
    print(f"  Testing {args.n_test_blocks} Poisson blocks...", flush=True)
    for i in range(args.n_test_blocks):
        seed = args.base_seed + 200000 + i
        sp = poisson_spacings(args.block_length, seed=seed)
        result = analyze_block(sp, ref_gue, ref_poi)
        result["true_type"] = "poisson"
        result["block_id"] = f"poi_test_{i:04d}"
        result["seed"] = seed
        all_results.append(result)
        if (i + 1) % 10 == 0:
            print(f"    poisson {i+1}/{args.n_test_blocks}", flush=True)

    dt = time.time() - t0
    print(f"\n  Analysis time: {dt:.1f}s", flush=True)

    # === Aggregate ===
    gue_results = [r for r in all_results if r["true_type"] == "gue"]
    poi_results = [r for r in all_results if r["true_type"] == "poisson"]

    # Accuracy: GUE blocks should vote "GUE", Poisson should vote "POISSON"
    gue_correct = sum(1 for r in gue_results if r.get("vote") == "GUE")
    poi_correct = sum(1 for r in poi_results if r.get("vote") == "POISSON")
    gue_accuracy = gue_correct / max(len(gue_results), 1)
    poi_accuracy = poi_correct / max(len(poi_results), 1)
    total_accuracy = (gue_correct + poi_correct) / max(len(all_results), 1)

    # Statistics
    gue_r_means = [r["r_mean"] for r in gue_results if "r_mean" in r]
    poi_r_means = [r["r_mean"] for r in poi_results if "r_mean" in r]
    gue_ks_margins = [r["ks_margin"] for r in gue_results if "ks_margin" in r]
    poi_ks_margins = [r["ks_margin"] for r in poi_results if "ks_margin" in r]
    gue_entropies = [r["entropy"] for r in gue_results if "entropy" in r]
    poi_entropies = [r["entropy"] for r in poi_results if "entropy" in r]

    print(f"\n{'='*80}", flush=True)
    print(f"RESULTS", flush=True)
    print(f"{'='*80}", flush=True)

    print(f"\n  --- Gap Ratio Mean (r_bar) ---", flush=True)
    print(f"  GUE blocks:     {np.mean(gue_r_means):.6f} +/- {np.std(gue_r_means):.6f} "
          f"(expected ~0.5996)", flush=True)
    print(f"  Poisson blocks: {np.mean(poi_r_means):.6f} +/- {np.std(poi_r_means):.6f} "
          f"(expected ~0.3863)", flush=True)

    print(f"\n  --- Histogram Entropy ---", flush=True)
    print(f"  GUE blocks:     {np.mean(gue_entropies):.4f} +/- {np.std(gue_entropies):.4f}", flush=True)
    print(f"  Poisson blocks: {np.mean(poi_entropies):.4f} +/- {np.std(poi_entropies):.4f}", flush=True)

    print(f"\n  --- KS Margin (KS_poi - KS_gue; positive = closer to GUE) ---", flush=True)
    print(f"  GUE blocks:     {np.mean(gue_ks_margins):+.6f} +/- {np.std(gue_ks_margins):.6f}", flush=True)
    print(f"  Poisson blocks: {np.mean(poi_ks_margins):+.6f} +/- {np.std(poi_ks_margins):.6f}", flush=True)

    print(f"\n  --- Classification Accuracy ---", flush=True)
    print(f"  GUE -> GUE:       {gue_correct}/{len(gue_results)} "
          f"({100*gue_accuracy:.1f}%)", flush=True)
    print(f"  Poisson -> Poisson: {poi_correct}/{len(poi_results)} "
          f"({100*poi_accuracy:.1f}%)", flush=True)
    print(f"  Total accuracy:   {gue_correct+poi_correct}/{len(all_results)} "
          f"({100*total_accuracy:.1f}%)", flush=True)

    # Sample per-block detail
    print(f"\n  --- Sample Blocks (first 5 of each) ---", flush=True)
    print(f"  {'block_id':<20} {'r_mean':>8} {'entropy':>8} "
          f"{'ks_gue':>8} {'ks_poi':>8} {'margin':>8} {'vote':>8}", flush=True)
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}", flush=True)
    for r in gue_results[:5]:
        print(f"  {r['block_id']:<20} {r.get('r_mean',0):8.4f} {r.get('entropy',0):8.4f} "
              f"{r.get('ks_gue_stat',0):8.4f} {r.get('ks_poi_stat',0):8.4f} "
              f"{r.get('ks_margin',0):+8.4f} {r.get('vote','?'):>8}", flush=True)
    for r in poi_results[:5]:
        print(f"  {r['block_id']:<20} {r.get('r_mean',0):8.4f} {r.get('entropy',0):8.4f} "
              f"{r.get('ks_gue_stat',0):8.4f} {r.get('ks_poi_stat',0):8.4f} "
              f"{r.get('ks_margin',0):+8.4f} {r.get('vote','?'):>8}", flush=True)

    # === Verdict ===
    aligned = gue_accuracy >= args.vote_threshold and poi_accuracy >= args.vote_threshold

    print(f"\n{'='*80}", flush=True)
    print(f"VERDICT", flush=True)
    print(f"{'='*80}", flush=True)

    if aligned:
        print(f"  STATUS: DISCRIMINATOR_VALIDATED", flush=True)
        print(f"  The gap-ratio KS discriminator separates GUE from Poisson at "
              f"{100*total_accuracy:.1f}% accuracy.", flush=True)
        print(f"  When applied to real zeta blocks, if KS(r, GUE) < KS(r, Poi) "
              f"in > {100*args.vote_threshold:.0f}% of blocks", flush=True)
        print(f"  -> 'GUE alignment confirmed'.", flush=True)
    else:
        print(f"  STATUS: DISCRIMINATOR_WEAK", flush=True)
        print(f"  Accuracy below threshold. Consider larger block_length "
              f"or more reference blocks.", flush=True)

    print(f"\n  DISCLAIMER: Statistical discrimination != proof of RH.", flush=True)
    print("", flush=True)

    # === Save JSON ===
    report = {
        "config": {
            "n_test_blocks": args.n_test_blocks,
            "n_ref_blocks": args.n_ref_blocks,
            "block_length": args.block_length,
            "vote_threshold": args.vote_threshold,
            "base_seed": args.base_seed,
        },
        "reference": {
            "gue_n_ratios": len(ref_gue),
            "gue_r_mean": round(float(np.mean(ref_gue)), 6),
            "poi_n_ratios": len(ref_poi),
            "poi_r_mean": round(float(np.mean(ref_poi)), 6),
        },
        "accuracy": {
            "gue_correct": gue_correct,
            "gue_total": len(gue_results),
            "gue_pct": round(100 * gue_accuracy, 2),
            "poi_correct": poi_correct,
            "poi_total": len(poi_results),
            "poi_pct": round(100 * poi_accuracy, 2),
            "total_pct": round(100 * total_accuracy, 2),
        },
        "stats": {
            "gue_r_mean": round(float(np.mean(gue_r_means)), 6),
            "gue_r_std": round(float(np.std(gue_r_means)), 6),
            "poi_r_mean": round(float(np.mean(poi_r_means)), 6),
            "poi_r_std": round(float(np.std(poi_r_means)), 6),
            "gue_ks_margin_mean": round(float(np.mean(gue_ks_margins)), 6),
            "poi_ks_margin_mean": round(float(np.mean(poi_ks_margins)), 6),
            "gue_entropy_mean": round(float(np.mean(gue_entropies)), 6),
            "poi_entropy_mean": round(float(np.mean(poi_entropies)), 6),
        },
        "verdict": "DISCRIMINATOR_VALIDATED" if aligned else "DISCRIMINATOR_WEAK",
        "time_s": round(dt, 1),
    }

    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "outputs", "gap_ratio_ks_report.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[SAVED] {json_path}", flush=True)

    return 0 if aligned else 1


if __name__ == "__main__":
    sys.exit(main())
