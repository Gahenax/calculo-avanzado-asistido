#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODLYZKO_FULL_AUDIT.py
=====================
Full gap-ratio KS audit on Odlyzko's 100k zeros.
Uses precomputed spacings from ODLYZKO_RIEMANN_PIPELINE.py.

Flow:
  1. Load spacings .npy
  2. Build GUE/Poisson reference distributions
  3. Cut into disjoint blocks (up to 499 blocks of 200 spacings)
  4. For each block x each entropy intensity → gap ratio → KS → vote
  5. Audit: per-type summary, robustness across intensities, outliers
  6. Final verdict

Usage:
    python src/ODLYZKO_FULL_AUDIT.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import numpy as np
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from controls import gue_spacings, poisson_spacings, build_disjoint_blocks_from_spacings
from metrics import gap_ratios, hist_entropy, ks_2samp
from entropy_reducer import entropy_reduce_1d
from io_utils import StreamingCSVWriter
from audit import run_audit

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ============================================================================
# CONFIG
# ============================================================================

SPACINGS_PATH = os.path.join("data", "spacings_odlyzko_zeros1.npy")
OUTPUT_DIR = os.path.join("data", "audit_100k")
MERGED_CSV = os.path.join(OUTPUT_DIR, "merged_100k.csv")
REPORT_JSON = os.path.join(OUTPUT_DIR, "audit_report_100k.json")
OUTLIERS_CSV = os.path.join(OUTPUT_DIR, "outliers_100k.csv")

BLOCK_LEN = 200
N_REF_BLOCKS = 80       # Reference blocks for GUE/Poisson distributions
CONTROL_BLOCKS = 100     # GUE + Poisson test blocks
GUE_MAT_N = 180
BULK_LO, BULK_HI = 0.2, 0.8

INTENSITIES = [
    {"name": "raw",    "median_k": 0,  "ema_alpha": 0,    "winsor_w": 0,  "p_lo": 0,   "p_hi": 100,  "ks_max": 1.0},
    {"name": "soft",   "median_k": 5,  "ema_alpha": 0.04, "winsor_w": 21, "p_lo": 2.5, "p_hi": 97.5, "ks_max": 0.18},
    {"name": "mid",    "median_k": 7,  "ema_alpha": 0.06, "winsor_w": 25, "p_lo": 2.5, "p_hi": 97.5, "ks_max": 0.16},
    {"name": "strong", "median_k": 9,  "ema_alpha": 0.08, "winsor_w": 31, "p_lo": 3.0, "p_hi": 97.0, "ks_max": 0.14},
]

CSV_COLUMNS = [
    "type", "block_id", "seed", "intensity",
    "r_mean", "r_std", "r_entropy",
    "ks_gue", "ks_poi", "ks_margin", "vote",
    "reducer_ks", "reducer_mode",
]


# ============================================================================
# PROCESS ONE BLOCK
# ============================================================================

def process_block(block: Dict[str, Any], intensity: Dict[str, Any],
                  r_gue_ref: np.ndarray, r_poi_ref: np.ndarray) -> Dict[str, Any]:
    """Process one block with one entropy intensity."""
    spacings = np.asarray(block["spacings"], dtype=np.float64)
    r = gap_ratios(spacings)

    if len(r) < 10:
        return {"type": block["type"], "block_id": block["block_id"],
                "vote": "INSUFFICIENT"}

    # Apply entropy reducer (skip for "raw")
    reducer_ks = 0.0
    reducer_mode = "none"
    if intensity["name"] != "raw" and intensity["median_k"] > 0:
        r_reduced, rinfo = entropy_reduce_1d(
            r,
            median_k=intensity["median_k"],
            ema_alpha=intensity["ema_alpha"],
            winsor_w=intensity["winsor_w"],
            p_lo=intensity["p_lo"],
            p_hi=intensity["p_hi"],
            ks_max=intensity["ks_max"],
        )
        reducer_ks = rinfo["ks"]
        reducer_mode = rinfo["mode"]
    else:
        r_reduced = r

    # Metrics
    from scipy import stats as _st
    r_mean = float(np.mean(r_reduced))
    r_std = float(np.std(r_reduced))
    r_ent = hist_entropy(r_reduced)

    ks_g = float(_st.ks_2samp(r_reduced, r_gue_ref).statistic)
    ks_p = float(_st.ks_2samp(r_reduced, r_poi_ref).statistic)
    margin = ks_p - ks_g
    vote = "GUE" if ks_g < ks_p else "POISSON"

    return {
        "type": block["type"],
        "block_id": block["block_id"],
        "seed": block.get("seed", 0),
        "intensity": intensity["name"],
        "r_mean": round(r_mean, 6),
        "r_std": round(r_std, 6),
        "r_entropy": round(r_ent, 6),
        "ks_gue": round(ks_g, 6),
        "ks_poi": round(ks_p, 6),
        "ks_margin": round(margin, 6),
        "vote": vote,
        "reducer_ks": round(reducer_ks, 6),
        "reducer_mode": reducer_mode,
    }


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "=" * 70, flush=True)
    print("  ODLYZKO 100K FULL AUDIT", flush=True)
    print("  Gap Ratio KS Discriminator x 4 intensities", flush=True)
    print("=" * 70 + "\n", flush=True)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    t0 = time.time()

    # === Load spacings ===
    print("[1/6] Loading Odlyzko spacings...", flush=True)
    spacings = np.load(SPACINGS_PATH)
    n_blocks_available = len(spacings) // BLOCK_LEN
    print(f"  Spacings: {len(spacings):,}", flush=True)
    print(f"  Available blocks (disjoint, {BLOCK_LEN} each): {n_blocks_available}", flush=True)

    # === Build reference distributions ===
    print("[2/6] Building reference gap-ratio distributions...", flush=True)
    ref_seed = 70000
    all_r_gue = [gap_ratios(gue_spacings(BLOCK_LEN, seed=ref_seed + i,
                  mat_n=GUE_MAT_N, bulk_lo=BULK_LO, bulk_hi=BULK_HI))
                  for i in range(N_REF_BLOCKS)]
    all_r_poi = [gap_ratios(poisson_spacings(BLOCK_LEN, seed=ref_seed + 10000 + i))
                  for i in range(N_REF_BLOCKS)]
    r_gue_ref = np.concatenate(all_r_gue)
    r_poi_ref = np.concatenate(all_r_poi)
    print(f"  GUE ref: {len(r_gue_ref):,} ratios (mean={np.mean(r_gue_ref):.4f})", flush=True)
    print(f"  POI ref: {len(r_poi_ref):,} ratios (mean={np.mean(r_poi_ref):.4f})", flush=True)

    # === Build blocks ===
    print("[3/6] Building disjoint blocks...", flush=True)

    # Zeta blocks (from Odlyzko)
    zeta_blocks = build_disjoint_blocks_from_spacings(
        spacings, n_blocks_available, BLOCK_LEN, seed=42, type_name="zeta"
    )

    # Control blocks
    gue_blocks = build_disjoint_blocks_from_spacings(
        np.array([]), CONTROL_BLOCKS, BLOCK_LEN, seed=80000, type_name="gue"
    )
    poi_blocks = build_disjoint_blocks_from_spacings(
        np.array([]), CONTROL_BLOCKS, BLOCK_LEN, seed=90000, type_name="poisson"
    )

    all_blocks = zeta_blocks + gue_blocks + poi_blocks
    print(f"  Zeta blocks: {len(zeta_blocks)}", flush=True)
    print(f"  GUE blocks:  {len(gue_blocks)}", flush=True)
    print(f"  POI blocks:  {len(poi_blocks)}", flush=True)
    print(f"  Total: {len(all_blocks)} x {len(INTENSITIES)} intensities "
          f"= {len(all_blocks) * len(INTENSITIES)} rows", flush=True)

    # === Process ===
    print("[4/6] Processing blocks...", flush=True)
    writer = StreamingCSVWriter(MERGED_CSV, flush_every=20)
    writer.write_header_once(CSV_COLUMNS)

    done = 0
    for bi, block in enumerate(all_blocks):
        for intensity in INTENSITIES:
            row = process_block(block, intensity, r_gue_ref, r_poi_ref)
            writer.write_rows([row])
        done += 1
        if done % 50 == 0 or done == len(all_blocks):
            print(f"    {done}/{len(all_blocks)} blocks "
                  f"({writer.total_rows} rows)", flush=True)

    writer.flush()
    process_time = time.time() - t0
    print(f"  Processing: {process_time:.1f}s", flush=True)
    print(f"  Merged CSV: {writer.file_size_mb:.2f} MB, {writer.total_rows} rows", flush=True)
    writer.close()

    # === Audit ===
    print("[5/6] Running audit...", flush=True)
    report = run_audit(MERGED_CSV, REPORT_JSON, OUTLIERS_CSV, topk=40)

    # === Print results ===
    print(f"\n[6/6] RESULTS", flush=True)
    print("=" * 70, flush=True)

    summary = report.get("summary_by_type_intensity", {})
    for key in sorted(summary.keys()):
        s = summary[key]
        print(f"  {key:<25} n={s['n_blocks']:>4}  "
              f"vote_GUE={s['vote_rate_gue']:>6.1%}  "
              f"margin={s['mean_ks_margin']:>+8.4f}  "
              f"r_mean={s['mean_r']:.4f}", flush=True)

    rob = report.get("robustness", {})
    if rob.get("zeta_available"):
        print(f"\n  ROBUSTNESS CHECK:", flush=True)
        passing = 0
        total_int = 0
        for intname, iv in rob.get("intensities", {}).items():
            status = "PASS" if iv["vote_rate"] > 0.6 else "FAIL"
            print(f"    {intname}: vote_rate={iv['vote_rate']:.1%} "
                  f"({iv['gue_votes']}/{iv['n']}) [{status}]", flush=True)
            total_int += 1
            if iv["vote_rate"] > 0.6:
                passing += 1

        robust = passing >= max(1, total_int * 2 // 3)

        print(f"\n{'='*70}", flush=True)
        if robust:
            print(f"  VERDICT: ZETA_ZEROS_FAVOR_GUE", flush=True)
            print(f"  Robust across {passing}/{total_int} intensities", flush=True)
            print(f"  100,000 Odlyzko zeros confirm GUE alignment", flush=True)
        else:
            print(f"  VERDICT: INCONCLUSIVE", flush=True)
            print(f"  Only {passing}/{total_int} intensities pass", flush=True)
    else:
        # Controls only
        print(f"\n  CONTROL VALIDATION:", flush=True)
        for key in sorted(summary.keys()):
            s = summary[key]
            expected = "GUE" if "gue" in key else "POISSON"
            actual_rate = s['vote_rate_gue']
            correct = (expected == "GUE" and actual_rate > 0.5) or \
                      (expected == "POISSON" and actual_rate < 0.5)
            print(f"    {key}: {'CORRECT' if correct else 'WRONG'}", flush=True)

    total_time = time.time() - t0
    print(f"\n  Total time: {total_time:.1f}s", flush=True)
    print(f"  DISCLAIMER: Statistical observation != proof of RH.", flush=True)
    print(f"  Outputs: {OUTPUT_DIR}/", flush=True)
    print("=" * 70, flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
