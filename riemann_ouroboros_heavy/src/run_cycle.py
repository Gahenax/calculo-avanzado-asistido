#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_cycle.py — OUROBOROS HEAVY main orchestrator.
Mines real zeta zeros, builds controls, runs gap-ratio KS analysis
across 3 entropy intensities, streams results, audits.

Usage:
    python src/run_cycle.py --config config.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import datetime
from multiprocessing import Pool, cpu_count
from typing import Dict, Any, List, Tuple

import numpy as np

# Ensure src/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from io_utils import StreamingCSVWriter
from controls import (gue_spacings, poisson_spacings,
                      build_disjoint_blocks_from_spacings)
from zeta_farmer import get_zeros_imag, compute_unfolded_spacings
from entropy_reducer import entropy_reduce_1d
from metrics import gap_ratios, hist_entropy
from pipeline import process_block
from audit import run_audit


# ============================================================================
# CSV column order
# ============================================================================

CSV_COLUMNS = [
    "iter", "type", "block_id", "seed", "intensity",
    "r_mean", "r_std", "r_entropy",
    "ks_gue", "ks_poi", "ks_margin", "vote",
    "reducer_ks", "reducer_mode", "reducer_entropy_delta",
]


# ============================================================================
# Worker (subprocess-safe)
# ============================================================================

def _worker(args: Tuple) -> List[Dict[str, Any]]:
    """Process one block across all intensities."""
    block, intensities, r_gue_ref, r_poi_ref, iteration = args

    rows = []
    for intensity in intensities:
        row = process_block(block, intensity, r_gue_ref, r_poi_ref)
        row["iter"] = iteration
        rows.append(row)
    return rows


# ============================================================================
# Logging
# ============================================================================

def log(msg: str, fh=None):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


# ============================================================================
# Main
# ============================================================================

def main():
    ap = argparse.ArgumentParser(description="OUROBOROS HEAVY - Riemann Cycle")
    ap.add_argument("--config", type=str, default="config.json")
    args = ap.parse_args()

    # Resolve paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # riemann_ouroboros_heavy/
    config_path = os.path.join(base_dir, args.config)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    output_dir = os.path.join(base_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    merged_csv = os.path.join(base_dir, cfg["io"]["merged_csv"])
    report_json = os.path.join(base_dir, cfg["audit"]["report_json"])
    outliers_csv = os.path.join(base_dir, cfg["audit"]["outliers_csv"])
    log_path = os.path.join(output_dir, "logs_cycle.txt")

    log_fh = open(log_path, "a", encoding="utf-8")

    log("=" * 72, log_fh)
    log("OUROBOROS HEAVY — Riemann Zeta GUE/Poisson Discriminator", log_fh)
    log(f"Config: {args.config}", log_fh)
    log(f"Max iterations: {cfg['max_iterations']}", log_fh)
    log(f"Zeta: {cfg['zeta']}", log_fh)
    log(f"Controls: gue={cfg['controls']['gue_blocks_per_iter']}, "
        f"poi={cfg['controls']['poisson_blocks_per_iter']}", log_fh)
    log("=" * 72, log_fh)

    max_iters = cfg["max_iterations"]
    zeta_cfg = cfg["zeta"]
    ctrl_cfg = cfg["controls"]
    reducer_cfg = cfg["entropy_reducer"]
    intensities = reducer_cfg.get("intensities", [])
    flush_every = cfg["io"].get("flush_every_blocks", 10)

    n_cores = cfg["parallel"].get("cores", -1)
    if n_cores <= 0:
        n_cores = max(1, cpu_count() - 1)

    # ======================================================================
    # Build reference distributions (large, from many control blocks)
    # ======================================================================
    log("[REF] Building reference gap-ratio distributions...", log_fh)
    ref_seed = 70000
    n_ref = 50  # blocks for reference
    ref_block_len = ctrl_cfg["block_spacings"]

    all_r_gue = []
    for i in range(n_ref):
        sp = gue_spacings(
            ref_block_len, seed=ref_seed + i,
            mat_n=ctrl_cfg["gue"]["mat_n"],
            bulk_lo=ctrl_cfg["gue"]["bulk_lo"],
            bulk_hi=ctrl_cfg["gue"]["bulk_hi"],
        )
        all_r_gue.append(gap_ratios(sp))

    all_r_poi = []
    for i in range(n_ref):
        sp = poisson_spacings(ref_block_len, seed=ref_seed + 10000 + i)
        all_r_poi.append(gap_ratios(sp))

    r_gue_ref = np.concatenate(all_r_gue)
    r_poi_ref = np.concatenate(all_r_poi)
    log(f"  GUE ref: {len(r_gue_ref)} ratios (mean={np.mean(r_gue_ref):.4f})", log_fh)
    log(f"  POI ref: {len(r_poi_ref)} ratios (mean={np.mean(r_poi_ref):.4f})", log_fh)

    # ======================================================================
    # Open merged CSV writer
    # ======================================================================
    writer = StreamingCSVWriter(merged_csv, flush_every=flush_every)
    writer.write_header_once(CSV_COLUMNS)

    grand_t0 = time.time()

    try:
        for iteration in range(max_iters):
            iter_t0 = time.time()
            iter_seed = 42 + iteration * 100000
            window = zeta_cfg["windows"][iteration] if iteration < len(zeta_cfg["windows"]) else None

            log(f"\n{'='*60}", log_fh)
            log(f"ITERATION {iteration + 1}/{max_iters} (seed={iter_seed})", log_fh)
            log(f"{'='*60}", log_fh)

            all_blocks = []

            # === ZETA blocks ===
            if zeta_cfg["enable"] and window:
                n_start = window["n_start"]
                n_end = window["n_end"]
                log(f"[ZETA] Farming zeros n=[{n_start}, {n_end})...", log_fh)

                t_imag = get_zeros_imag(
                    n_start, n_end,
                    dps=zeta_cfg["dps"],
                    cache_dir=output_dir,
                )

                spacings = compute_unfolded_spacings(t_imag)
                log(f"  Unfolded: {len(spacings)} spacings, "
                    f"mean={np.mean(spacings):.4f}", log_fh)

                n_zeta_blocks = zeta_cfg["blocks_per_iter"]
                block_len = zeta_cfg["block_spacings"]
                zeta_blocks = build_disjoint_blocks_from_spacings(
                    spacings, n_zeta_blocks, block_len,
                    seed=iter_seed, type_name="zeta"
                )
                all_blocks.extend(zeta_blocks)
                log(f"  Zeta blocks: {len(zeta_blocks)}", log_fh)

            # === GUE blocks ===
            n_gue = ctrl_cfg["gue_blocks_per_iter"]
            gue_blocks = build_disjoint_blocks_from_spacings(
                np.array([]), n_gue, ctrl_cfg["block_spacings"],
                seed=iter_seed + 1000, type_name="gue"
            )
            all_blocks.extend(gue_blocks)

            # === Poisson blocks ===
            n_poi = ctrl_cfg["poisson_blocks_per_iter"]
            poi_blocks = build_disjoint_blocks_from_spacings(
                np.array([]), n_poi, ctrl_cfg["block_spacings"],
                seed=iter_seed + 2000, type_name="poisson"
            )
            all_blocks.extend(poi_blocks)

            log(f"  Total blocks: {len(all_blocks)} "
                f"(zeta={len(all_blocks)-n_gue-n_poi}, "
                f"gue={n_gue}, poi={n_poi})", log_fh)

            # === Process all blocks x all intensities ===
            worker_args = [
                (block, intensities, r_gue_ref, r_poi_ref, iteration)
                for block in all_blocks
            ]

            processed = 0
            try:
                pool_size = min(n_cores, len(worker_args))
                if pool_size < 1:
                    pool_size = 1
                with Pool(processes=pool_size) as pool:
                    for result_rows in pool.imap_unordered(_worker, worker_args):
                        writer.write_rows(result_rows)
                        processed += 1
                        if processed % 20 == 0 or processed == len(all_blocks):
                            log(f"    blocks: {processed}/{len(all_blocks)} "
                                f"rows={writer.total_rows}", log_fh)
            except Exception as e:
                log(f"  Pool error ({e}), sequential fallback", log_fh)
                for wa in worker_args:
                    result_rows = _worker(wa)
                    writer.write_rows(result_rows)
                    processed += 1
                    if processed % 20 == 0 or processed == len(all_blocks):
                        log(f"    blocks: {processed}/{len(all_blocks)} "
                            f"rows={writer.total_rows}", log_fh)

            writer.flush()
            iter_dt = time.time() - iter_t0
            log(f"  Iteration time: {iter_dt:.1f}s | "
                f"merged: {writer.file_size_mb:.2f} MB | "
                f"total rows: {writer.total_rows}", log_fh)

            # === Audit ===
            report = run_audit(merged_csv, report_json, outliers_csv,
                               topk=cfg["audit"].get("topk_outliers", 40))

            # Print summary
            log(f"  AUDIT SUMMARY:", log_fh)
            for key, s in report.get("summary_by_type_intensity", {}).items():
                log(f"    {key}: n={s['n_blocks']} "
                    f"vote_GUE={s['vote_rate_gue']:.0%} "
                    f"margin={s['mean_ks_margin']:+.4f} "
                    f"r_mean={s['mean_r']:.4f}", log_fh)

            rob = report.get("robustness", {})
            if rob.get("zeta_available"):
                log(f"  ROBUSTNESS: passing={rob['passing_intensities']}/{rob['total_intensities']} "
                    f"robust={rob['robust']}", log_fh)

    finally:
        final_mb = writer.file_size_mb
        final_rows = writer.total_rows
        writer.close()

    grand_dt = time.time() - grand_t0

    # === Final conclusion ===
    print(f"\n{'='*72}", flush=True)
    print(f"OUROBOROS HEAVY — FINAL REPORT", flush=True)
    print(f"{'='*72}", flush=True)
    print(f"  Total time: {grand_dt:.0f}s ({grand_dt/60:.1f}min)", flush=True)
    print(f"  Merged CSV: {final_mb:.2f} MB, {final_rows} rows", flush=True)

    # Load final audit
    if os.path.exists(report_json):
        with open(report_json, "r") as f:
            final_report = json.load(f)

        rob = final_report.get("robustness", {})
        if rob.get("zeta_available"):
            if rob.get("robust"):
                print(f"  CONCLUSION: ZETA FAVORS GUE "
                      f"(robust across {rob['passing_intensities']}/{rob['total_intensities']} intensities)",
                      flush=True)
            else:
                print(f"  CONCLUSION: INCONCLUSIVE "
                      f"({rob['passing_intensities']}/{rob['total_intensities']} intensities pass)",
                      flush=True)

            for intname, iv in rob.get("intensities", {}).items():
                print(f"    {intname}: vote_rate={iv['vote_rate']:.0%} "
                      f"({iv['gue_votes']}/{iv['n']})", flush=True)
        else:
            print(f"  No zeta blocks analyzed (controls only).", flush=True)

    print(f"\n  DISCLAIMER: Statistical observation != proof of RH.", flush=True)
    print(f"  Outputs: {output_dir}/", flush=True)

    log_fh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
