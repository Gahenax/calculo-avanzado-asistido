#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
farm_window.py — Standalone zeta zero farmer for one window.
Designed for parallel execution (e.g., 4 Jules tasks).

Usage:
    python farm_window.py --n_start 1000 --n_end 11050 --window_id 1
    python farm_window.py --n_start 12000 --n_end 22050 --window_id 2
    python farm_window.py --n_start 23000 --n_end 33050 --window_id 3
    python farm_window.py --n_start 34000 --n_end 44050 --window_id 4

Output:
    outputs/zeros_window_{window_id}.npy       - raw Im(zetazero(n))
    outputs/spacings_window_{window_id}.npy    - unfolded spacings
    outputs/farm_report_{window_id}.json       - timing + stats
"""
import argparse
import json
import os
import sys
import time
import numpy as np
import mpmath


def get_zeros_imag(n_start: int, n_end: int, dps: int,
                   cache_path: str) -> np.ndarray:
    """Mine Im(zetazero(n)) with incremental checkpointing."""
    mpmath.mp.dps = dps
    count = n_end - n_start

    # Full cache hit
    if os.path.exists(cache_path):
        cached = np.load(cache_path)
        if len(cached) == count:
            print(f"  [CACHE HIT] {cache_path} ({count} zeros)", flush=True)
            return cached

    # Partial resume
    partial_path = cache_path + ".partial.npy"
    start_idx = 0
    zeros = np.zeros(count, dtype=np.float64)

    if os.path.exists(partial_path):
        partial = np.load(partial_path)
        start_idx = len(partial)
        zeros[:start_idx] = partial
        print(f"  [RESUME] from {start_idx}/{count}", flush=True)

    t0 = time.time()
    for i in range(start_idx, count):
        n = n_start + i
        z = mpmath.zetazero(n)
        zeros[i] = float(z.imag)

        elapsed = time.time() - t0
        done = i - start_idx + 1
        if done % 50 == 0 or i == count - 1:
            rate = done / max(elapsed, 0.01)
            remaining = (count - i - 1) / max(rate, 0.001)
            print(f"    [{done}/{count - start_idx}] n={n} "
                  f"t={zeros[i]:.2f} "
                  f"rate={rate:.2f}/s "
                  f"ETA={remaining/60:.1f}min", flush=True)

        # Checkpoint every 200 zeros
        if done % 200 == 0:
            np.save(partial_path, zeros[:i + 1])

    np.save(cache_path, zeros)
    if os.path.exists(partial_path):
        os.remove(partial_path)

    total_time = time.time() - t0
    print(f"  [DONE] {count} zeros in {total_time:.0f}s "
          f"({count/max(total_time,0.01):.2f}/s)", flush=True)
    return zeros


def compute_unfolded_spacings(t_imag: np.ndarray) -> np.ndarray:
    """Riemann-von Mangoldt unfolding."""
    t = np.sort(t_imag)
    t = t[t > 0]
    two_pi = 2.0 * np.pi
    t_over_2pi = t / two_pi
    N = t_over_2pi * np.log(t_over_2pi) - t_over_2pi + 7.0 / 8.0
    spacings = np.diff(N)
    mean_s = np.mean(spacings)
    if mean_s > 0:
        spacings = spacings / mean_s
    return spacings


def main():
    ap = argparse.ArgumentParser(description="Farm one zeta window")
    ap.add_argument("--n_start", type=int, required=True)
    ap.add_argument("--n_end", type=int, required=True)
    ap.add_argument("--window_id", type=int, required=True)
    ap.add_argument("--dps", type=int, default=50)
    ap.add_argument("--output_dir", type=str, default="outputs")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    wid = args.window_id

    print(f"\n{'='*60}", flush=True)
    print(f"ZETA FARMER — Window {wid}", flush=True)
    print(f"  n=[{args.n_start}, {args.n_end})", flush=True)
    print(f"  count={args.n_end - args.n_start}", flush=True)
    print(f"  dps={args.dps}", flush=True)
    print(f"{'='*60}\n", flush=True)

    t0 = time.time()

    # Farm zeros
    zeros_path = os.path.join(args.output_dir, f"zeros_window_{wid}.npy")
    zeros = get_zeros_imag(args.n_start, args.n_end, args.dps, zeros_path)

    # Unfold
    spacings = compute_unfolded_spacings(zeros)
    spacings_path = os.path.join(args.output_dir, f"spacings_window_{wid}.npy")
    np.save(spacings_path, spacings)

    total_time = time.time() - t0

    # Report
    report = {
        "window_id": wid,
        "n_start": args.n_start,
        "n_end": args.n_end,
        "n_zeros": len(zeros),
        "n_spacings": len(spacings),
        "dps": args.dps,
        "time_s": round(total_time, 1),
        "time_min": round(total_time / 60, 1),
        "rate_zeros_per_s": round(len(zeros) / max(total_time, 0.01), 3),
        "spacings_mean": round(float(np.mean(spacings)), 6),
        "spacings_std": round(float(np.std(spacings)), 6),
        "t_min": round(float(np.min(zeros)), 4),
        "t_max": round(float(np.max(zeros)), 4),
        "zeros_path": zeros_path,
        "spacings_path": spacings_path,
    }

    report_path = os.path.join(args.output_dir, f"farm_report_{wid}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}", flush=True)
    print(f"FARM COMPLETE — Window {wid}", flush=True)
    print(f"  Zeros: {len(zeros)}", flush=True)
    print(f"  Spacings: {len(spacings)} (mean={np.mean(spacings):.4f})", flush=True)
    print(f"  Time: {total_time:.0f}s ({total_time/60:.1f}min)", flush=True)
    print(f"  Files: {zeros_path}, {spacings_path}", flush=True)
    print(f"{'='*60}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
