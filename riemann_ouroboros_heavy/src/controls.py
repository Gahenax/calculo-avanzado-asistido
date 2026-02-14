#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
controls.py — GUE and Poisson synthetic control generators for OUROBOROS HEAVY.
All code self-contained; only uses numpy.
"""
import numpy as np
from typing import List, Dict, Any


def poisson_spacings(n: int, seed: int = 42) -> np.ndarray:
    """Generate n Poisson spacings ~ Exp(1)."""
    rng = np.random.default_rng(seed)
    return rng.exponential(1.0, n)


def gue_spacings(n: int, seed: int = 42, mat_n: int = 180,
                 bulk_lo: float = 0.2, bulk_hi: float = 0.8) -> np.ndarray:
    """
    Generate n GUE spacings from random Hermitian matrices.
    Bulk eigenvalues only, unfolded (mean=1).
    """
    rng = np.random.default_rng(seed)
    all_sp = []

    while len(all_sp) < n:
        G = rng.standard_normal((mat_n, mat_n)) + \
            1j * rng.standard_normal((mat_n, mat_n))
        H = (G + G.conj().T) / np.sqrt(2.0 * mat_n)
        vals = np.linalg.eigvalsh(H).real
        vals.sort()

        lo = int(bulk_lo * mat_n)
        hi = int(bulk_hi * mat_n)
        bulk = vals[lo:hi]
        if len(bulk) < 3:
            continue

        s = np.diff(bulk)
        m = np.mean(s)
        if m > 0:
            s = s / m
        all_sp.extend(s.tolist())

    return np.array(all_sp[:n], dtype=np.float64)


def build_disjoint_blocks_from_spacings(
    spacings: np.ndarray,
    n_blocks: int,
    block_len: int,
    seed: int,
    type_name: str,
) -> List[Dict[str, Any]]:
    """
    Cut spacings into n_blocks disjoint blocks of block_len.
    For gue/poisson types, generates fresh spacings per block if input is empty.
    """
    blocks = []
    total = len(spacings)

    for i in range(n_blocks):
        block_seed = seed * 1000 + i

        if total >= (i + 1) * block_len:
            # Use from provided array (disjoint)
            start = i * block_len
            sp = spacings[start:start + block_len].copy()
        elif type_name.lower() == "gue":
            sp = gue_spacings(block_len, seed=block_seed)
        elif type_name.lower() == "poisson":
            sp = poisson_spacings(block_len, seed=block_seed)
        else:
            continue  # not enough input data

        blocks.append({
            "type": type_name,
            "block_id": f"{type_name}_{seed}_{i:04d}",
            "seed": block_seed,
            "spacings": sp,
        })

    return blocks
