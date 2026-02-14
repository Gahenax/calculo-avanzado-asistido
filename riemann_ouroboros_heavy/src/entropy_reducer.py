#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entropy_reducer.py — 1D entropy reduction with 3 intensity levels.
Pipeline: rolling median -> EMA -> local winsorization.
Guardrail: KS test degrades intensity if distortion exceeds ks_max.
"""
import numpy as np
from scipy import stats
from typing import Tuple, Dict, Any


def _rolling_median(x: np.ndarray, k: int) -> np.ndarray:
    """Rolling median with reflect padding."""
    n = len(x)
    if k < 3 or n < k:
        return x.copy()
    half = k // 2
    padded = np.pad(x, half, mode="reflect")
    out = np.empty(n, dtype=x.dtype)
    for i in range(n):
        out[i] = np.median(padded[i:i + k])
    return out


def _ema(x: np.ndarray, alpha: float) -> np.ndarray:
    """Exponential moving average (forward pass)."""
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def _local_winsorize(x: np.ndarray, w: int, p_lo: float, p_hi: float) -> np.ndarray:
    """Local windowed winsorization via chunk percentile clipping."""
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
    x_c = x[np.isfinite(x)]
    if len(x_c) < 10:
        return 0.0
    hist, _ = np.histogram(x_c, bins=bins, density=True)
    hist = hist[hist > 0]
    rng = x_c.max() - x_c.min()
    dx = rng / bins if rng > 0 else 1.0
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
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Full entropy reduction pipeline with KS guardrail.

    Returns: (reduced_series, info_dict)
    """
    x = np.asarray(x, dtype=np.float64)
    entropy_before = _entropy_proxy(x)

    # Stage 1: Rolling median
    y = _rolling_median(x, median_k)

    # Stage 2: EMA
    y = _ema(y, ema_alpha)

    # Stage 3: Local winsorization
    y_full = _local_winsorize(y, winsor_w, p_lo, p_hi)

    # KS guardrail
    ks_stat, _ = stats.ks_2samp(x, y_full)
    mode = "full"
    y_out = y_full

    if ks_stat > ks_max:
        # Degrade: skip winsorization
        ks2, _ = stats.ks_2samp(x, y)
        if ks2 <= ks_max:
            y_out = y
            mode = "no_winsor"
            ks_stat = ks2
        else:
            # Degrade further: minimal median only
            y_min = _rolling_median(x, max(3, median_k // 2))
            ks3, _ = stats.ks_2samp(x, y_min)
            y_out = y_min
            mode = "minimal"
            ks_stat = ks3

    entropy_after = _entropy_proxy(y_out)

    info = {
        "ks": round(float(ks_stat), 6),
        "mode": mode,
        "entropy_before": round(entropy_before, 6),
        "entropy_after": round(entropy_after, 6),
        "entropy_delta": round(entropy_after - entropy_before, 6),
    }
    return y_out, info
