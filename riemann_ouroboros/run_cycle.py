#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_cycle.py
============
OUROBOROS main orchestrator.
Cycle: Build Blocks -> Reduce -> Embed -> Flow -> Stream Write -> Audit -> Repeat.

Uses multiprocessing Pool for (reduce+embed+flow) per block.
Parent process writes merged CSV (single-writer streaming).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import datetime
from multiprocessing import Pool, cpu_count
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

# Ensure our package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entropy_reducer import entropy_reduce_1d
from embeddings import compute_gap_ratios, build_cloud, subsample_cloud, normalize_cloud
from controls import build_blocks_from_spacings, gue_spacings, poisson_spacings
from farmer_adapter import has_zeta_farmer, get_zeta_blocks
from flow_on_cloud import run_flow_on_cloud
from io_utils import MergedWriter, prepare_history_rows
from audit import run_audit


# ===========================================================================
# Worker function (runs in subprocess)
# ===========================================================================

def _process_block(args: Tuple) -> Tuple[str, str, int, str, List[Dict], Dict]:
    """
    Worker: process a single block.
    Returns: (block_id, block_type, seed, embed_name, history_rows, reducer_info)
    """
    (block, run_id, flow_steps, flow_points, flow_float32,
     reducer_cfg, embed_dim) = args

    block_id = block["block_id"]
    block_type = block["type"]
    block_seed = block["seed"]
    spacings = np.array(block["spacings"], dtype=np.float64)

    # 1) Gap ratios
    gr = compute_gap_ratios(spacings)

    # 2) Entropy reduction (optional)
    reducer_info = {"mode": "none", "ks_stat": 0.0,
                    "entropy_before": 0.0, "entropy_after": 0.0}
    series = gr
    if reducer_cfg.get("enable", False):
        series, reducer_info = entropy_reduce_1d(
            gr,
            median_k=reducer_cfg.get("median_k", 7),
            ema_alpha=reducer_cfg.get("ema_alpha", 0.06),
            winsor_w=reducer_cfg.get("winsor_w", 25),
            p_lo=reducer_cfg.get("winsor_p_lo", 2.5),
            p_hi=reducer_cfg.get("winsor_p_hi", 97.5),
            ks_max=reducer_cfg.get("ks_max", 0.15),
        )

    # 3) Embedding
    X = build_cloud(series, dim=embed_dim)
    X = subsample_cloud(X, flow_points, seed=block_seed)
    X_norm, embed_meta = normalize_cloud(X)

    # 4) Flow
    history = run_flow_on_cloud(
        X_norm, seed=block_seed, steps=flow_steps, float32=flow_float32
    )

    # 5) Prepare rows with metadata
    rows = prepare_history_rows(
        history=history,
        run_id=run_id,
        block_id=block_id,
        block_type=block_type,
        block_seed=block_seed,
        embed_name="gap_ratio_3d",
        reducer_info=reducer_info,
    )

    return (block_id, block_type, block_seed, "gap_ratio_3d", rows, reducer_info)


# ===========================================================================
# Cycle state persistence
# ===========================================================================

def load_cycle_state(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "iteration": 0,
        "base_seed": 42,
        "seen_blocks": 0,
        "last_summaries": [],
        "stop_reasons": [],
    }


def save_cycle_state(state: Dict[str, Any], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)


# ===========================================================================
# Logging
# ===========================================================================

def log(msg: str, log_file=None):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        log_file.write(line + "\n")
        log_file.flush()


# ===========================================================================
# Main cycle
# ===========================================================================

def main():
    ap = argparse.ArgumentParser(description="OUROBOROS-RH LAB: Main Cycle")
    ap.add_argument("--config", type=str, default="config.json")
    args = ap.parse_args()

    # Load config
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.config)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "data", "outputs")
    os.makedirs(output_dir, exist_ok=True)

    merged_path = os.path.join(output_dir, "merged_flow_traces.csv")
    state_path = os.path.join(output_dir, "cycle_state.json")
    log_path = os.path.join(output_dir, "logs_cycle.txt")

    # Open log
    log_file = open(log_path, "a", encoding="utf-8")

    log("=" * 70, log_file)
    log("OUROBOROS-RH LAB  --  Cycle Start", log_file)
    log(f"Config: {args.config}", log_file)
    log(f"Max iterations: {cfg['max_iterations']}", log_file)
    log(f"Blocks/iter: {cfg['blocks_per_iter']}", log_file)
    log(f"Flow: steps={cfg['flow_steps']}, points={cfg['flow_points']}", log_file)
    log("=" * 70, log_file)

    # Load or init state
    state = load_cycle_state(state_path)
    start_iter = state["iteration"]
    base_seed = state["base_seed"]

    max_iters = cfg["max_iterations"]
    blocks_cfg = cfg["blocks_per_iter"]
    block_len = cfg["block_length_spacings"]
    flow_steps = cfg["flow_steps"]
    flow_points = cfg["flow_points"]
    flow_f32 = cfg.get("flow_float32", True)
    reducer_cfg = cfg.get("entropy_reducer", {})
    audit_cfg = cfg.get("audit", {})
    embed_dim = 3

    n_cores = cfg.get("cores", -1)
    if n_cores <= 0:
        n_cores = max(1, cpu_count() - 1)

    # Open merged writer
    writer = MergedWriter(merged_path, flush_every=3)

    previous_summary = None
    stagnation_count = 0

    try:
        for iteration in range(start_iter, start_iter + max_iters):
            iter_seed = base_seed + iteration * 10000
            log(f"\n--- Iteration {iteration + 1}/{start_iter + max_iters} (seed={iter_seed}) ---", log_file)
            t0 = time.time()

            # === Build blocks ===
            all_blocks = []

            # Zeta blocks (if farmer available)
            n_zeta = blocks_cfg.get("zeta", 0)
            if n_zeta > 0 and has_zeta_farmer():
                zeta_blocks = get_zeta_blocks(state, n_zeta, block_len, iter_seed)
                all_blocks.extend(zeta_blocks)
                log(f"  Zeta blocks: {len(zeta_blocks)}", log_file)

            # GUE blocks
            n_gue = blocks_cfg.get("gue", 0)
            if n_gue > 0:
                gue_blocks = build_blocks_from_spacings(
                    np.array([]), block_len, n_gue, iter_seed + 1000, "gue"
                )
                all_blocks.extend(gue_blocks)

            # Poisson blocks
            n_poi = blocks_cfg.get("poisson", 0)
            if n_poi > 0:
                poi_blocks = build_blocks_from_spacings(
                    np.array([]), block_len, n_poi, iter_seed + 2000, "poisson"
                )
                all_blocks.extend(poi_blocks)

            log(f"  Total blocks: {len(all_blocks)} (gue={n_gue}, poisson={n_poi})", log_file)

            # === Process blocks (parallel) ===
            worker_args = [
                (block, iteration, flow_steps, flow_points, flow_f32,
                 reducer_cfg, embed_dim)
                for block in all_blocks
            ]

            processed = 0
            ks_violations = 0

            # Use pool for parallelism; fall back to sequential if pool fails
            try:
                with Pool(processes=min(n_cores, len(worker_args))) as pool:
                    for result in pool.imap_unordered(_process_block, worker_args):
                        block_id, block_type, seed, embed, rows, r_info = result
                        writer.write_block_history(rows)
                        processed += 1

                        if r_info.get("ks_stat", 0) > reducer_cfg.get("ks_max", 0.15):
                            ks_violations += 1

                        if processed % 5 == 0 or processed == len(all_blocks):
                            log(f"    processed {processed}/{len(all_blocks)} "
                                f"({block_type}) rows={writer.total_rows}", log_file)
            except Exception as e:
                log(f"  Pool failed ({e}), falling back to sequential", log_file)
                for wa in worker_args:
                    result = _process_block(wa)
                    block_id, block_type, seed, embed, rows, r_info = result
                    writer.write_block_history(rows)
                    processed += 1

                    if r_info.get("ks_stat", 0) > reducer_cfg.get("ks_max", 0.15):
                        ks_violations += 1

                    if processed % 5 == 0 or processed == len(all_blocks):
                        log(f"    processed {processed}/{len(all_blocks)} "
                            f"({block_type}) rows={writer.total_rows}", log_file)

            dt = time.time() - t0
            log(f"  Iteration time: {dt:.1f}s | merged: {writer.file_size_mb:.2f} MB | "
                f"total rows: {writer.total_rows}", log_file)

            # === Audit ===
            writer._file.flush()
            report = run_audit(
                merged_csv_path=merged_path,
                output_dir=output_dir,
                topk=audit_cfg.get("outlier_topk", 30),
            )

            # Print summary
            log(f"  AUDIT:", log_file)
            for btype, s in report.get("summary_by_type", {}).items():
                log(f"    {btype}: n={s['n_blocks']} converged={s['pct_converged']:.0f}% "
                    f"stalled={s['pct_stalled']:.0f}%", log_file)

            if report.get("top_outliers"):
                log(f"  TOP OUTLIERS:", log_file)
                for o in report["top_outliers"][:5]:
                    log(f"    {o['block_id']}: score={o['outlier_score']:.4f} "
                        f"d_gue={o['d_gue']:.4f} d_poi={o['d_poi']:.4f} "
                        f"status={o['status']}", log_file)

            # === Stop conditions ===
            state["iteration"] = iteration + 1
            state["seen_blocks"] += processed

            # Check stagnation
            current_summary = report.get("summary_by_type", {})
            if previous_summary is not None:
                changed = False
                for btype in current_summary:
                    if btype in previous_summary:
                        prev_conv = previous_summary[btype].get("pct_converged", 0)
                        curr_conv = current_summary[btype].get("pct_converged", 0)
                        if abs(curr_conv - prev_conv) > 1.0:
                            changed = True
                if not changed:
                    stagnation_count += 1
                else:
                    stagnation_count = 0
            previous_summary = current_summary

            # KS violation check
            ks_pct = 100 * ks_violations / max(processed, 1)
            if ks_pct > 20:
                state["stop_reasons"].append(
                    f"iter={iteration+1}: KS violations {ks_pct:.0f}% > 20%"
                )
                log(f"  STOP: KS guardrail violations ({ks_pct:.0f}%)", log_file)
                break

            if stagnation_count >= 2:
                state["stop_reasons"].append(
                    f"iter={iteration+1}: stagnation for 2 consecutive iters"
                )
                log(f"  STOP: Metrics stagnant for 2 iterations", log_file)
                break

            save_cycle_state(state, state_path)

        # === Final ===
        state["stop_reasons"].append(f"completed max_iterations={max_iters}")
        save_cycle_state(state, state_path)

    finally:
        final_mb = writer.file_size_mb
        final_rows = writer.total_rows
        writer.close()
        log_file.close()

    print(f"\n[OUROBOROS] Cycle complete. Outputs in {output_dir}/", flush=True)
    print(f"  merged_flow_traces.csv: {final_mb:.2f} MB, {final_rows} rows", flush=True)
    print(f"  audit_report.json, outliers.csv, cycle_state.json", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
