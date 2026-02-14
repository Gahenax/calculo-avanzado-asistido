#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assemble_and_audit.py — Collect farmed windows, run full pipeline + audit.
Run AFTER all 4 farm_window.py tasks complete.

Usage:
    python src/assemble_and_audit.py --config config.json
"""
import argparse
import json
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from controls import gue_spacings, poisson_spacings, build_disjoint_blocks_from_spacings
from entropy_reducer import entropy_reduce_1d
from metrics import gap_ratios, hist_entropy
from pipeline import process_block
from io_utils import StreamingCSVWriter
from audit import run_audit


CSV_COLUMNS = [
    "iter", "type", "block_id", "seed", "intensity",
    "r_mean", "r_std", "r_entropy",
    "ks_gue", "ks_poi", "ks_margin", "vote",
    "reducer_ks", "reducer_mode", "reducer_entropy_delta",
]


def main():
    ap = argparse.ArgumentParser(description="Assemble farmed windows + audit")
    ap.add_argument("--config", type=str, default="config.json")
    args = ap.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    config_path = os.path.join(base_dir, args.config)

    with open(config_path, "r") as f:
        cfg = json.load(f)

    output_dir = os.path.join(base_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    merged_csv = os.path.join(base_dir, cfg["io"]["merged_csv"])
    report_json = os.path.join(base_dir, cfg["audit"]["report_json"])
    outliers_csv = os.path.join(base_dir, cfg["audit"]["outliers_csv"])

    ctrl_cfg = cfg["controls"]
    reducer_cfg = cfg["entropy_reducer"]
    intensities = reducer_cfg.get("intensities", [])
    zeta_cfg = cfg["zeta"]

    print("=" * 60, flush=True)
    print("ASSEMBLE & AUDIT — Collecting farmed windows", flush=True)
    print("=" * 60, flush=True)

    # === Check which windows are available ===
    windows = cfg["zeta"]["windows"]
    available = []
    for i, w in enumerate(windows):
        wid = i + 1
        sp_path = os.path.join(output_dir, f"spacings_window_{wid}.npy")
        z_path = os.path.join(output_dir, f"zeros_window_{wid}.npy")
        if os.path.exists(sp_path):
            spacings = np.load(sp_path)
            available.append((wid, w, spacings))
            print(f"  Window {wid}: FOUND ({len(spacings)} spacings)", flush=True)
        elif os.path.exists(z_path):
            # spacings not computed yet, compute now
            zeros = np.load(z_path)
            from zeta_farmer import compute_unfolded_spacings
            spacings = compute_unfolded_spacings(zeros)
            np.save(sp_path, spacings)
            available.append((wid, w, spacings))
            print(f"  Window {wid}: COMPUTED ({len(spacings)} spacings)", flush=True)
        else:
            print(f"  Window {wid}: MISSING", flush=True)

    if not available:
        print("\nERROR: No farmed windows found. Run farm_window.py first.", flush=True)
        return 1

    # === Build reference distributions ===
    print(f"\n[REF] Building reference gap-ratio distributions...", flush=True)
    ref_seed = 70000
    n_ref = 50
    block_sp = ctrl_cfg["block_spacings"]

    all_r_gue = [gap_ratios(gue_spacings(block_sp, seed=ref_seed + i,
                  mat_n=ctrl_cfg["gue"]["mat_n"],
                  bulk_lo=ctrl_cfg["gue"]["bulk_lo"],
                  bulk_hi=ctrl_cfg["gue"]["bulk_hi"]))
                  for i in range(n_ref)]
    all_r_poi = [gap_ratios(poisson_spacings(block_sp, seed=ref_seed + 10000 + i))
                  for i in range(n_ref)]
    r_gue_ref = np.concatenate(all_r_gue)
    r_poi_ref = np.concatenate(all_r_poi)
    print(f"  GUE ref: {len(r_gue_ref)} (mean={np.mean(r_gue_ref):.4f})", flush=True)
    print(f"  POI ref: {len(r_poi_ref)} (mean={np.mean(r_poi_ref):.4f})", flush=True)

    # === Process all windows ===
    writer = StreamingCSVWriter(merged_csv, flush_every=5)
    writer.write_header_once(CSV_COLUMNS)
    t0 = time.time()

    for wid, window, spacings in available:
        iter_seed = 42 + (wid - 1) * 100000
        print(f"\n[WINDOW {wid}] Processing {len(spacings)} spacings...", flush=True)

        # Zeta blocks (disjoint)
        n_blocks = zeta_cfg["blocks_per_iter"]
        block_len = zeta_cfg["block_spacings"]
        zeta_blocks = build_disjoint_blocks_from_spacings(
            spacings, n_blocks, block_len, iter_seed, "zeta"
        )

        # Control blocks
        gue_blocks = build_disjoint_blocks_from_spacings(
            np.array([]), ctrl_cfg["gue_blocks_per_iter"],
            block_sp, iter_seed + 1000, "gue"
        )
        poi_blocks = build_disjoint_blocks_from_spacings(
            np.array([]), ctrl_cfg["poisson_blocks_per_iter"],
            block_sp, iter_seed + 2000, "poisson"
        )

        all_blocks = zeta_blocks + gue_blocks + poi_blocks
        print(f"  Blocks: {len(zeta_blocks)} zeta + "
              f"{len(gue_blocks)} gue + {len(poi_blocks)} poi", flush=True)

        # Process each block x each intensity
        for bi, block in enumerate(all_blocks):
            for intensity in intensities:
                row = process_block(block, intensity, r_gue_ref, r_poi_ref)
                row["iter"] = wid - 1
                writer.write_rows([row])

            if (bi + 1) % 25 == 0 or bi == len(all_blocks) - 1:
                print(f"    blocks: {bi+1}/{len(all_blocks)} "
                      f"rows={writer.total_rows}", flush=True)

    writer.flush()
    final_mb = writer.file_size_mb
    final_rows = writer.total_rows
    writer.close()

    dt = time.time() - t0
    print(f"\n  Assembly time: {dt:.1f}s", flush=True)
    print(f"  Merged: {final_mb:.2f} MB, {final_rows} rows", flush=True)

    # === Audit ===
    print(f"\n[AUDIT] Running final audit...", flush=True)
    report = run_audit(merged_csv, report_json, outliers_csv,
                       topk=cfg["audit"].get("topk_outliers", 40))

    print(f"\n{'='*60}", flush=True)
    print(f"FINAL REPORT", flush=True)
    print(f"{'='*60}", flush=True)

    for key, s in report.get("summary_by_type_intensity", {}).items():
        print(f"  {key}: n={s['n_blocks']} "
              f"vote_GUE={s['vote_rate_gue']:.0%} "
              f"margin={s['mean_ks_margin']:+.4f}", flush=True)

    rob = report.get("robustness", {})
    if rob.get("zeta_available"):
        status = "ZETA_FAVORS_GUE" if rob.get("robust") else "INCONCLUSIVE"
        print(f"\n  CONCLUSION: {status}", flush=True)
        for intname, iv in rob.get("intensities", {}).items():
            print(f"    {intname}: vote_rate={iv['vote_rate']:.0%}", flush=True)

    print(f"\n  DISCLAIMER: Statistical observation != proof of RH.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
