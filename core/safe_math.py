# -*- coding: utf-8 -*-
# safe_math.py
from __future__ import annotations

import numpy as np
from dataclasses import dataclass


@dataclass
class SanityStats:
    clamp_log1p_frac: float = 0.0
    clamp_log1p_count: int = 0
    clamp_sqrt_count: int = 0
    clamp_div_count: int = 0
    nonfinite_hits: int = 0


def sanitize_array(x: np.ndarray, stats: SanityStats) -> np.ndarray:
    m = ~np.isfinite(x)
    if m.any():
        stats.nonfinite_hits += int(m.sum())
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x


def safe_log1p(x: np.ndarray, eps_dom: float, stats: SanityStats) -> np.ndarray:
    lo = -1.0 + eps_dom
    m = x <= lo
    if m.any():
        stats.clamp_log1p_count += int(m.sum())
        stats.clamp_log1p_frac = float(m.mean())
        x = x.copy()
        x[m] = lo
    return np.log1p(x)


def safe_sqrt(x: np.ndarray, eps_dom: float, stats: SanityStats) -> np.ndarray:
    m = x < 0.0
    if m.any():
        stats.clamp_sqrt_count += int(m.sum())
        x = x.copy()
        x[m] = 0.0
    return np.sqrt(x + eps_dom)


def safe_div(a: np.ndarray, b: np.ndarray, eps_div: float, stats: SanityStats) -> np.ndarray:
    m = np.abs(b) < eps_div
    if m.any():
        stats.clamp_div_count += int(m.sum())
        b = b.copy()
        b[m] = np.sign(b[m]) * eps_div
        b[b == 0.0] = eps_div
    return a / b
