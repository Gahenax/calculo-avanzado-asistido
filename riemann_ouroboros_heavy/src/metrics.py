#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics.py — Gap ratio and KS distance metrics for OUROBOROS HEAVY.
"""
import numpy as np
from scipy import stats
from typing import Dict, Any


def gap_ratios(spacings: np.ndarray) -> np.ndarray:
    """r_i = min(s_i, s_{i+1}) / max(s_i, s_{i+1})."""
    s = np.asarray(spacings, dtype=np.float64)
    s = s[np.isfinite(s) & (s > 0)]
    if len(s) < 3:
        return np.array([])
    s0 = s[:-1]
    s1 = s[1:]
    eps = 1e-30
    return np.minimum(s0, s1) / (np.maximum(s0, s1) + eps)


def hist_entropy(r: np.ndarray, bins: int = 50,
                 range_: tuple = (0, 1)) -> float:
    """Shannon entropy of gap ratio histogram."""
    if len(r) < 5:
        return 0.0
    hist, _ = np.histogram(r, bins=bins, range=range_, density=True)
    hist = hist[hist > 0]
    dx = (range_[1] - range_[0]) / bins
    p = hist * dx
    p = p[p > 0]
    return -float(np.sum(p * np.log(p + 1e-30)))


def ks_2samp(a: np.ndarray, b: np.ndarray) -> float:
    """KS 2-sample statistic (just the statistic, not p-value)."""
    result = stats.ks_2samp(a, b)
    return float(result.statistic)


def block_metrics(spacings: np.ndarray,
                  r_gue_ref: np.ndarray,
                  r_poi_ref: np.ndarray) -> Dict[str, Any]:
    """
    Compute all metrics for a single block of spacings.

    Returns dict with: r_mean, r_std, r_entropy,
    ks_gue, ks_poi, ks_margin, vote
    """
    r = gap_ratios(spacings)
    if len(r) < 10:
        return {
            "r_mean": 0.0, "r_std": 0.0, "r_entropy": 0.0,
            "ks_gue": 1.0, "ks_poi": 1.0, "ks_margin": 0.0,
            "vote": "INSUFFICIENT",
        }

    r_mean = float(np.mean(r))
    r_std = float(np.std(r))
    r_ent = hist_entropy(r)

    ks_gue = ks_2samp(r, r_gue_ref)
    ks_poi = ks_2samp(r, r_poi_ref)
    margin = ks_poi - ks_gue

    vote = "GUE" if ks_gue < ks_poi else "POISSON"

    return {
        "r_mean": round(r_mean, 6),
        "r_std": round(r_std, 6),
        "r_entropy": round(r_ent, 6),
        "ks_gue": round(ks_gue, 6),
        "ks_poi": round(ks_poi, 6),
        "ks_margin": round(margin, 6),
        "vote": vote,
    }
