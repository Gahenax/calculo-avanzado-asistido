#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — Per-block processing for OUROBOROS HEAVY.
Applies: spacings -> gap ratios -> entropy reducer -> metrics vs controls.
"""
import numpy as np
from typing import Dict, Any, Tuple

from entropy_reducer import entropy_reduce_1d
from metrics import gap_ratios, block_metrics


def process_block(
    block: Dict[str, Any],
    intensity: Dict[str, Any],
    r_gue_ref: np.ndarray,
    r_poi_ref: np.ndarray,
) -> Dict[str, Any]:
    """
    Process one block with one entropy intensity.

    Args:
        block: dict with type, block_id, seed, spacings
        intensity: dict with name, median_k, ema_alpha, winsor_w, p_lo, p_hi, ks_max
        r_gue_ref: reference gap ratio distribution (GUE)
        r_poi_ref: reference gap ratio distribution (Poisson)

    Returns: flat dict row for merged CSV.
    """
    spacings = np.asarray(block["spacings"], dtype=np.float64)

    # Compute raw gap ratios
    r_raw = gap_ratios(spacings)

    # Apply entropy reducer on gap ratios
    reducer_info = {"ks": 0.0, "mode": "none", "entropy_before": 0.0,
                    "entropy_after": 0.0, "entropy_delta": 0.0}

    if intensity.get("name") != "none" and len(r_raw) > 20:
        r_reduced, reducer_info = entropy_reduce_1d(
            r_raw,
            median_k=intensity["median_k"],
            ema_alpha=intensity["ema_alpha"],
            winsor_w=intensity["winsor_w"],
            p_lo=intensity["p_lo"],
            p_hi=intensity["p_hi"],
            ks_max=intensity["ks_max"],
        )
    else:
        r_reduced = r_raw

    # Compute metrics (using reduced gap ratios vs reference)
    # But we need spacings for gap_ratios inside block_metrics
    # So we pass the reduced ratios directly to KS
    from scipy import stats as _st
    r_mean = float(np.mean(r_reduced)) if len(r_reduced) > 0 else 0.0
    r_std = float(np.std(r_reduced)) if len(r_reduced) > 0 else 0.0

    # Histogram entropy of reduced
    from metrics import hist_entropy
    r_ent = hist_entropy(r_reduced)

    # KS vs controls
    ks_gue = float(_st.ks_2samp(r_reduced, r_gue_ref).statistic) if len(r_reduced) > 5 else 1.0
    ks_poi = float(_st.ks_2samp(r_reduced, r_poi_ref).statistic) if len(r_reduced) > 5 else 1.0
    margin = ks_poi - ks_gue
    vote = "GUE" if ks_gue < ks_poi else "POISSON"

    return {
        "type": block["type"],
        "block_id": block["block_id"],
        "seed": block["seed"],
        "intensity": intensity.get("name", "none"),
        "r_mean": round(r_mean, 6),
        "r_std": round(r_std, 6),
        "r_entropy": round(r_ent, 6),
        "ks_gue": round(ks_gue, 6),
        "ks_poi": round(ks_poi, 6),
        "ks_margin": round(margin, 6),
        "vote": vote,
        "reducer_ks": reducer_info.get("ks", 0.0),
        "reducer_mode": reducer_info.get("mode", "none"),
        "reducer_entropy_delta": reducer_info.get("entropy_delta", 0.0),
    }
