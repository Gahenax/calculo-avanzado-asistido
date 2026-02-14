#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POINT_CLOUD_LAPLACIAN_FLOW_HARDENED_V2_1.py
============================================
Laplacian-based diffusion flow on 3D point clouds.
Hardened v2.1: float32 support, adaptive dt, convergence/stall detection.

DO NOT MODIFY — used as engine by OUROBOROS lab.
Author: GAHENAX Core
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from scipy.spatial import cKDTree


@dataclass
class FlowState:
    step: int = 0
    time: float = 0.0
    radius_mean: float = 0.0
    radius_var: float = 0.0
    sphericity: float = 0.0
    laplacian_energy: float = 0.0
    mean_flow_norm: float = 0.0
    max_flow_norm: float = 0.0
    status: str = "running"  # running | converged | stalled


class PointCloudLaplacianFlow:
    """
    Laplacian smoothing flow on a 3D point cloud.
    At each step, each point moves toward the centroid of its k nearest neighbors.
    """

    def __init__(self, n_points: int = 1000, seed: int = 42,
                 use_float32: bool = True, k_neighbors: int = 12,
                 dt: float = 0.05, conv_tol: float = 1e-6,
                 stall_window: int = 20, stall_tol: float = 1e-8):
        self.n_points = n_points
        self.seed = seed
        self.use_float32 = use_float32
        self.k_neighbors = min(k_neighbors, max(3, n_points - 1))
        self.dt = dt
        self.conv_tol = conv_tol
        self.stall_window = stall_window
        self.stall_tol = stall_tol

        dtype = np.float32 if use_float32 else np.float64
        rng = np.random.default_rng(seed)
        self.points = rng.standard_normal((n_points, 3)).astype(dtype)
        self.history: List[FlowState] = []
        self.time: float = 0.0
        self._recent_energies: List[float] = []

    def _compute_laplacian(self) -> np.ndarray:
        """Compute graph Laplacian displacement: each point -> mean of k-NN minus self."""
        tree = cKDTree(self.points)
        k = self.k_neighbors + 1  # include self
        _, idx = tree.query(self.points, k=k)
        neighbors = self.points[idx[:, 1:]]  # exclude self
        centroid = neighbors.mean(axis=1)
        return centroid - self.points

    def _compute_state(self, step: int, flow: np.ndarray) -> FlowState:
        """Compute flow state metrics."""
        centroid = self.points.mean(axis=0)
        radii = np.linalg.norm(self.points - centroid, axis=1)
        r_mean = float(np.mean(radii))
        r_var = float(np.var(radii))

        # Sphericity: ratio of min/max eigenvalue of covariance
        cov = np.cov(self.points.T)
        eigvals = np.linalg.eigvalsh(cov)
        eigvals = np.clip(eigvals, 1e-30, None)
        sphericity = float(eigvals.min() / eigvals.max()) if eigvals.max() > 0 else 0.0

        # Laplacian energy: sum of squared displacements
        lap_energy = float(np.mean(np.sum(flow**2, axis=1)))

        flow_norms = np.linalg.norm(flow, axis=1)
        mean_fn = float(np.mean(flow_norms))
        max_fn = float(np.max(flow_norms))

        # Convergence/stall detection
        status = "running"
        if mean_fn < self.conv_tol:
            status = "converged"

        self._recent_energies.append(lap_energy)
        if len(self._recent_energies) > self.stall_window:
            self._recent_energies = self._recent_energies[-self.stall_window:]
        if len(self._recent_energies) >= self.stall_window:
            e_arr = np.array(self._recent_energies)
            if np.std(e_arr) < self.stall_tol and status != "converged":
                status = "stalled"

        return FlowState(
            step=step,
            time=self.time,
            radius_mean=round(r_mean, 8),
            radius_var=round(r_var, 8),
            sphericity=round(sphericity, 8),
            laplacian_energy=round(lap_energy, 10),
            mean_flow_norm=round(mean_fn, 10),
            max_flow_norm=round(max_fn, 10),
            status=status,
        )

    def step_once(self) -> FlowState:
        """Execute one flow step."""
        flow = self._compute_laplacian()
        self.points = self.points + self.dt * flow
        self.time += self.dt

        state = self._compute_state(len(self.history), flow)
        self.history.append(state)
        return state

    def run(self, steps: int = 100, log_every: int = 10,
            early_stop: bool = True) -> List[FlowState]:
        """Run flow for given steps."""
        for i in range(steps):
            state = self.step_once()
            if i % log_every == 0 or i == steps - 1:
                pass  # caller can inspect history
            if early_stop and state.status in ("converged", "stalled"):
                break
        return self.history
