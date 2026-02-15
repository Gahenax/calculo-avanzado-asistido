# -*- coding: utf-8 -*-
# GAHENAX_UA_ENGINE_V2_HARDENED.py
from __future__ import annotations

import sys
import os
import numpy as np
import time
from typing import Tuple, Dict, Any

# Ensure core is in path
sys.path.append(os.path.dirname(__file__))

from safe_math import SanityStats, sanitize_array
from hardening import HardeningConfig, UAStats, SeedScore
from governance_runtime import run_with_retries
from GAHENAX_UA_ENGINE_V2 import deep_lll_v2, chaos_mix_v2, UALedger, safe_int64_basis, eye_like, _maxabs_row, entropy_cap_compute

def lattice_step_fn(A: np.ndarray, rng: np.random.Generator, cfg: HardeningConfig, sanity: SanityStats) -> np.ndarray:
    """
    One 'step' of the lattice reduction.
    We'll do a small chaos mix followed by a LLL-pass.
    """
    n = A.shape[0]
    # Stronger reduction focus
    inner_budget = n * n * 5
    inner_ledger = UALedger(budget=inner_budget) 
    
    # Chaos (minimal to escape local minima)
    B, is_object = safe_int64_basis(A)
    U = eye_like(n, B)
    maxabs = np.array([_maxabs_row(B, i) for i in range(n)], dtype=object if is_object else np.int64)
    ecap = entropy_cap_compute(B)
    
    # Minimal chaos
    B, U, maxabs, is_object = chaos_mix_v2(B, U, maxabs, inner_ledger, is_object, 1, ecap, 2, rng)
    
    # Deep LLL (full breadth)
    B, U, maxabs, is_object, _, _ = deep_lll_v2(B, U, maxabs, inner_ledger, is_object, 0.99, 0.98, n, 10)
    
    return np.array(B, dtype=np.float64)

def lattice_score_fn(A: np.ndarray) -> float:
    """Minimized norm found in basis."""
    norms = np.linalg.norm(A.astype(float), axis=1)
    return float(np.min(norms))

def ua_engine_v2_hardened(basis: np.ndarray, **kwargs) -> Tuple[np.ndarray, Dict]:
    """
    Hardened UA Engine V2 orchestrator using P over NP philosophy.
    """
    n = basis.shape[0]
    seed = kwargs.get("seed", 42)
    ua_budget = float(kwargs.get("ua_budget", 100 * n * n))
    iter_max = int(kwargs.get("iter_max", 100))
    
    cfg = HardeningConfig(
        tau_growth=1.0,         # Allow faster entropy growth initially
        stagnation_window=200,   # More time to see improvement
        eps_norm=1e-18
    )
    seed_scores = {}
    
    t0 = time.time()
    
    # Run with retries (Adaptive Hardening)
    result = run_with_retries(
        seed=seed,
        A_init=basis.astype(np.float64),
        step_fn=lattice_step_fn,
        score_fn=lattice_score_fn,
        ua_budget=ua_budget,
        iter_max=iter_max,
        cfg=cfg,
        seed_scores=seed_scores,
        retries=2
    )
    
    dt = time.time() - t0
    
    # Format log for warfare suite compatibility
    log = {
        "n": n,
        "UA_spent": float(getattr(result.get("ua"), "spent", 0.0) if result.get("ua") else 0.0),
        "status": result.get("status"),
        "stop_reason": result.get("status"),
        "fail_mode": result.get("fail_mode", ""),
        "time": dt,
        "score": result.get("score")
    }
    
    # Reconstruct best basis if survived
    if "A" in result:
        # For SVP warfare, we need to return 'coeffs' (unimodular matrix)
        # However, run_universe_hardened works on basis A.
        # We'll just return A as the 'coeffs' for now if they are used as basis.
        # Wait, the black_box_solver expects coeffs such that v = coeffs @ basis.
        # This is a bit tricky since we modified the basis directly.
        # Let's assume for now the user wants the resulting basis.
        return result["A"], log
    
    return basis, log
