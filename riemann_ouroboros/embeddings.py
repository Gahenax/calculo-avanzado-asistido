#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embeddings.py
=============
Gap-ratio computation and 3D time-delay embedding for spectral series.
"""
import numpy as np


def compute_gap_ratios(spacings: np.ndarray) -> np.ndarray:
    """
    Compute consecutive gap ratios: r_i = min(s_i, s_{i+1}) / max(s_i, s_{i+1}).
    GUE target: <r> ~ 0.60, Poisson target: <r> ~ 0.386.
    """
    s = np.asarray(spacings, dtype=np.float64)
    s0 = s[:-1]
    s1 = s[1:]
    eps = 1e-30
    r = np.minimum(s0, s1) / (np.maximum(s0, s1) + eps)
    return r


def build_cloud(series: np.ndarray, dim: int = 3) -> np.ndarray:
    """
    Build time-delay embedding: X_i = (v_i, v_{i+1}, ..., v_{i+dim-1}).
    Returns: (N-dim+1, dim) array.
    """
    v = np.asarray(series, dtype=np.float64)
    n = len(v)
    if n < dim + 1:
        raise ValueError(f"Series too short ({n}) for dim={dim}.")
    rows = n - dim + 1
    X = np.empty((rows, dim), dtype=np.float64)
    for d in range(dim):
        X[:, d] = v[d:d + rows]
    return X


def subsample_cloud(X: np.ndarray, max_points: int, seed: int = 0) -> np.ndarray:
    """Subsample cloud to max_points if it exceeds."""
    if X.shape[0] <= max_points:
        return X
    rng = np.random.default_rng(seed)
    idx = rng.choice(X.shape[0], size=max_points, replace=False)
    idx.sort()
    return X[idx]


def normalize_cloud(X: np.ndarray) -> tuple:
    """
    Z-score normalization per dimension with soft clip at [1st, 99th] percentile.
    Returns: (X_norm, meta_dict).
    """
    X = np.asarray(X, dtype=np.float64)
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds = np.where(stds < 1e-12, 1.0, stds)
    X_norm = (X - means) / stds

    # Soft clip to percentiles
    for d in range(X_norm.shape[1]):
        lo = np.percentile(X_norm[:, d], 1.0)
        hi = np.percentile(X_norm[:, d], 99.0)
        X_norm[:, d] = np.clip(X_norm[:, d], lo, hi)

    meta = {
        "means": means.tolist(),
        "stds": stds.tolist(),
        "n_points": int(X_norm.shape[0]),
        "dim": int(X_norm.shape[1]),
    }
    return X_norm, meta


def full_embedding_pipeline(spacings: np.ndarray, dim: int = 3,
                            max_points: int = 1500,
                            seed: int = 0) -> tuple:
    """
    Full pipeline: spacings -> gap ratios -> cloud -> subsample -> normalize.
    Returns: (X_norm, meta).
    """
    gr = compute_gap_ratios(spacings)
    X = build_cloud(gr, dim=dim)
    X = subsample_cloud(X, max_points, seed=seed)
    X_norm, meta = normalize_cloud(X)
    meta["embedding"] = "gap_ratio_3d"
    meta["gap_ratio_mean"] = round(float(np.mean(gr)), 6)
    return X_norm, meta
