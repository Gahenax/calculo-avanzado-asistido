#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
farmer_adapter.py
=================
Adapter for real zeta zero farmer. Default: stub (no farmer available).
If a real farmer exists, integrate here without touching the rest.
"""
from typing import List, Dict, Any


def has_zeta_farmer() -> bool:
    """Check if a real zeta zero farmer is available."""
    return False


def get_zeta_blocks(iter_state: dict, n_blocks: int,
                    block_length: int, seed: int) -> List[Dict[str, Any]]:
    """
    Fetch zeta zero blocks from a real farmer.
    Default: returns empty list.
    """
    if not has_zeta_farmer():
        return []

    # --- INTEGRATION POINT ---
    # When a real farmer exists (e.g. mpmath.zetazero miner),
    # implement here:
    # 1. Mine zeros using iter_state for progress tracking
    # 2. Unfold using Riemann-von Mangoldt N(T)
    # 3. Cut into blocks of block_length spacings
    # 4. Return list of dicts with keys: type, block_id, seed, spacings
    return []
