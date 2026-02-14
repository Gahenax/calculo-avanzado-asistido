#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entropy_reducer.py
==================
1D entropy reduction pipeline for spectral series.
Pipeline: rolling median -> EMA -> local winsorization.
Guardrail: KS test degrades intensity if distribution distortion is too high.
"""
import numpy as np
from scipy import stats


def _rolling_median(x: np.ndarray, k: int) -> np.ndarray:
    """Rolling median filter (centered, edge-padded)."""
    n = len(x)
    if k < 3 or n < k:
        return x.copy()
    half = k // 2
    out = np.empty(n, dtype=x.dtype)
    padded = np.concatenate([np.full(half, x[0]), x, np.full(half, x[-1])])
    for i in range(n):
        out[i] = np.median(padded[i:i + k])
    return out


def _ema(x: np.ndarray, alpha: float) -> np.ndarray:
    """Exponential moving average."""
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def _local_winsorize(x: np.ndarray, w: int, p_lo: float, p_hi: float) -> np.ndarray:
    """Local windowed winsorization."""
    n = len(x)
    if w < 5 or n < w:
        return x.copy()
    half = w // 2
    out = x.copy()
    for i in range(n):
        lo_idx = max(0, i - half)
        hi_idx = min(n, i + half + 1)
        window = x[lo_idx:hi_idx]
        vlo = np.percentile(window, p_lo)
        vhi = np.percentile(window, p_hi)
        out[i] = np.clip(x[i], vlo, vhi)
    return out


def _entropy_proxy(x: np.ndarray, bins: int = 50) -> float:
    """Shannon entropy proxy via histogram."""
    x_clean = x[np.isfinite(x)]
    if len(x_clean) < 10:
        return 0.0
    hist, _ = np.histogram(x_clean, bins=bins, density=True)
    hist = hist[hist > 0]
    dx = (x_clean.max() - x_clean.min()) / bins if x_clean.max() > x_clean.min() else 1.0
    p = hist * dx
    p = p[p > 0]
    return -float(np.sum(p * np.log(p + 1e-30)))


def entropy_reduce_1d(
    x: np.ndarray,
    median_k: int = 7,
    ema_alpha: float = 0.06,
    winsor_w: int = 25,
    p_lo: float = 2.5,
    p_hi: float = 97.5,
    ks_max: float = 0.15,
) -> tuple:
    """
    Full entropy reduction pipeline with guardrail.

    Returns:
        (y, info_dict) where y is the reduced series and info_dict contains metrics.
    """
    x = np.asarray(x, dtype=np.float64)
    entropy_before = _entropy_proxy(x)
    mad_before = float(np.median(np.abs(x - np.median(x))))

    # Stage 1: Rolling median
    y = _rolling_median(x, median_k)

    # Stage 2: EMA
    y = _ema(y, ema_alpha)

    # Stage 3: Local winsorization
    y_full = _local_winsorize(y, winsor_w, p_lo, p_hi)

    # Guardrail: KS test between original and reduced
    ks_stat, ks_pval = stats.ks_2samp(x, y_full)

    mode = "full"
    y_out = y_full

    if ks_stat > ks_max:
        # Degrade: skip winsorization
        y_no_winsor = y.copy()
        ks2, _ = stats.ks_2samp(x, y_no_winsor)
        if ks2 <= ks_max:
            y_out = y_no_winsor
            mode = "no_winsor"
            ks_stat = ks2
        else:
            # Degrade further: larger median window only
            y_med_only = _rolling_median(x, max(3, median_k // 2))
            ks3, _ = stats.ks_2samp(x, y_med_only)
            y_out = y_med_only
            mode = "minimal"
            ks_stat = ks3

    entropy_after = _entropy_proxy(y_out)
    mad_after = float(np.median(np.abs(y_out - np.median(y_out))))

    info = {
        "entropy_before": round(entropy_before, 6),
        "entropy_after": round(entropy_after, 6),
        "entropy_delta": round(entropy_after - entropy_before, 6),
        "mad_before": round(mad_before, 6),
        "mad_after": round(mad_after, 6),
        "ks_stat": round(float(ks_stat), 6),
        "mode": mode,
    }
    return y_out, info
