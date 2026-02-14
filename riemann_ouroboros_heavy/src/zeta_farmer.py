#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zeta_farmer.py — Mine Riemann zeta zeros via mpmath with caching + unfolding.
Self-contained: only uses mpmath + numpy + stdlib.
"""
import os
import time
import numpy as np
import mpmath


def get_zeros_imag(n_start: int, n_end: int, dps: int = 50,
                   cache_dir: str = "outputs") -> np.ndarray:
    """
    Compute Im(zetazero(n)) for n in [n_start, n_end).
    Uses incremental numpy cache to allow resuming.

    Returns: float64 array of imaginary parts.
    """
    mpmath.mp.dps = dps
    count = n_end - n_start
    cache_path = os.path.join(cache_dir, f"zeros_imag_{n_start}_{n_end}.npy")

    # Try loading cache
    if os.path.exists(cache_path):
        cached = np.load(cache_path)
        if len(cached) == count:
            print(f"  [CACHE HIT] {cache_path} ({count} zeros)", flush=True)
            return cached

    # Partial cache check
    partial_path = cache_path + ".partial.npy"
    start_idx = 0
    zeros = np.zeros(count, dtype=np.float64)

    if os.path.exists(partial_path):
        partial = np.load(partial_path)
        start_idx = len(partial)
        zeros[:start_idx] = partial
        print(f"  [RESUME] from {start_idx}/{count}", flush=True)

    # Mine remaining
    t0 = time.time()
    save_interval = 100  # save partial every N zeros

    for i in range(start_idx, count):
        n = n_start + i
        z = mpmath.zetazero(n)
        zeros[i] = float(z.imag)

        elapsed = time.time() - t0
        done = i - start_idx + 1
        if done % 50 == 0 or i == count - 1:
            rate = done / max(elapsed, 0.01)
            remaining = (count - i - 1) / max(rate, 0.001)
            print(f"    zero {i+1}/{count} (n={n}) "
                  f"t={zeros[i]:.4f} "
                  f"rate={rate:.2f}/s "
                  f"ETA={remaining/60:.1f}min", flush=True)

        # Save partial checkpoint
        if done % save_interval == 0:
            np.save(partial_path, zeros[:i + 1])

    # Save final
    np.save(cache_path, zeros)
    if os.path.exists(partial_path):
        os.remove(partial_path)

    total_time = time.time() - t0
    print(f"  [FARMED] {count} zeros in {total_time:.1f}s "
          f"({count/max(total_time,0.01):.2f}/s)", flush=True)

    return zeros


def compute_unfolded_spacings(t_imag: np.ndarray) -> np.ndarray:
    """
    Unfold zeros using Riemann-von Mangoldt N(T) approximation.

    N(T) = (T/(2*pi)) * log(T/(2*pi)) - T/(2*pi) + 7/8

    Returns: normalized spacings (mean ≈ 1).
    """
    t = np.sort(t_imag)
    t = t[t > 0]  # safety

    two_pi = 2.0 * np.pi
    t_over_2pi = t / two_pi

    # N(T) = (T/2pi) * log(T/2pi) - T/2pi + 7/8
    N = t_over_2pi * np.log(t_over_2pi) - t_over_2pi + 7.0 / 8.0

    spacings = np.diff(N)

    # Normalize by mean to ensure mean≈1
    mean_s = np.mean(spacings)
    if mean_s > 0:
        spacings = spacings / mean_s

    return spacings
