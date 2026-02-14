#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flow_on_cloud.py
================
Wrapper around POINT_CLOUD_LAPLACIAN_FLOW_HARDENED_V2_1.
Does NOT modify the engine — only wraps it for the OUROBOROS pipeline.
"""
import numpy as np
from dataclasses import asdict
from typing import List, Dict, Any
import sys
import os

# Ensure the ouroboros directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from POINT_CLOUD_LAPLACIAN_FLOW_HARDENED_V2_1 import PointCloudLaplacianFlow


def run_flow_on_cloud(X: np.ndarray, seed: int, steps: int,
                      float32: bool = True) -> List[Dict[str, Any]]:
    """
    Run Laplacian flow on a pre-built point cloud.

    Args:
        X: (N, 3) point cloud (already embedded and normalized)
        seed: random seed for the flow engine
        steps: number of flow steps
        float32: use float32 precision

    Returns:
        List of FlowState dicts (one per step)
    """
    n_points = X.shape[0]
    dtype = np.float32 if float32 else np.float64

    sim = PointCloudLaplacianFlow(
        n_points=n_points,
        seed=seed,
        use_float32=float32,
    )

    # Override initial cloud with our embedded data
    sim.points = X.astype(dtype, copy=False)
    sim.history = []
    sim.time = 0.0
    sim._recent_energies = []

    # Run flow (log_every very high to avoid noise; we capture all in history)
    sim.run(steps=steps, log_every=10**9)

    return [asdict(st) for st in sim.history]
