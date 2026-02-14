#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
controls.py
===========
Synthetic control generators: GUE (Hermitian matrices) and Poisson (exponential).
"""
import numpy as np
from typing import List, Dict, Any


def poisson_spacings(n: int, seed: int = 42) -> np.ndarray:
    """Generate n Poisson spacings (Exp(1))."""
    rng = np.random.default_rng(seed)
    return rng.exponential(1.0, n)


def gue_spacings(n: int, seed: int = 42, mat_n: int = 180,
                 bulk: tuple = (0.2, 0.8)) -> np.ndarray:
    """
    Generate n GUE spacings from random Hermitian matrices.
    Uses bulk eigenvalues only (Wigner semicircle interior).
    Concatenates matrices until we reach n spacings.
    """
    rng = np.random.default_rng(seed)
    all_spacings = []
    batch = 0

    while len(all_spacings) < n:
        # GUE matrix: A = (G + G^H) / sqrt(2N)
        G = rng.standard_normal((mat_n, mat_n)) + \
            1j * rng.standard_normal((mat_n, mat_n))
        H = (G + G.conj().T) / np.sqrt(2.0 * mat_n)
        vals = np.linalg.eigvalsh(H).real
        vals.sort()

        # Take bulk
        lo = int(bulk[0] * mat_n)
        hi = int(bulk[1] * mat_n)
        bulk_vals = vals[lo:hi]

        if len(bulk_vals) < 3:
            batch += 1
            continue

        s = np.diff(bulk_vals)
        mean_s = np.mean(s)
        if mean_s > 0:
            s = s / mean_s  # unfold: mean=1

        all_spacings.extend(s.tolist())
        batch += 1

    return np.array(all_spacings[:n], dtype=np.float64)


def build_blocks_from_spacings(
    spacings: np.ndarray,
    block_length: int,
    n_blocks: int,
    seed: int,
    type_name: str,
) -> List[Dict[str, Any]]:
    """
    Cut disjoint blocks from a spacings array.
    Uses pseudorandom offsets for variety.
    """
    rng = np.random.default_rng(seed)
    total = len(spacings)
    blocks = []

    if total < block_length and type_name.lower() not in ("gue", "poisson"):
        # Only return early for non-synthetic types that need input data
        return blocks

    # Maximum number of disjoint blocks
    max_disjoint = total // block_length
    if max_disjoint < n_blocks:
        # Wrap around with different seeds
        pass

    for i in range(n_blocks):
        # For each block, generate fresh spacings with unique seed
        block_seed = seed * 1000 + i
        if type_name.lower() == "gue":
            sp = gue_spacings(block_length, seed=block_seed)
        elif type_name.lower() == "poisson":
            sp = poisson_spacings(block_length, seed=block_seed)
        else:
            # Use from array
            start = (i * block_length) % (total - block_length + 1)
            sp = spacings[start:start + block_length]

        blocks.append({
            "type": type_name,
            "block_id": f"{type_name}_{seed}_{i:04d}",
            "seed": block_seed,
            "spacings": sp.tolist() if isinstance(sp, np.ndarray) else sp,
        })

    return blocks
