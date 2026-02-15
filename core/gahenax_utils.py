# -*- coding: utf-8 -*-
# gahenax_utils.py
from __future__ import annotations

import time
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Tuple, List, Any, Dict, Optional

# ============================================================
# A) ATHENA GOVERNANCE (UA)
# ============================================================

@dataclass
class UALedger:
    """
    Unified Ledger for Athena Units (UA).
    Tracks detailed work breakdown.
    """
    budget: int = 0
    mix: int = 0
    purge_try: int = 0
    purge_exec: int = 0
    gs_full: int = 0
    lll_step: int = 0
    deep_search: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def spent(self) -> int:
        return (self.mix + self.purge_try + self.purge_exec +
                self.gs_full + self.lll_step + self.deep_search)

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    def alive(self) -> bool:
        return self.spent < self.budget

    def pay(self, kind: str, amount: int = 1) -> bool:
        if not self.alive():
            return False
        current = getattr(self, kind, 0)
        setattr(self, kind, current + amount)
        return True

    def add_budget(self, amount: int) -> None:
        if amount > 0:
            self.budget += int(amount)

    def snapshot(self) -> dict:
        return {
            "budget": self.budget, "spent": self.spent,
            "breakdown": {
                "mix": self.mix, "purge_try": self.purge_try,
                "purge_exec": self.purge_exec, "gs_full": self.gs_full,
                "lll_step": self.lll_step, "deep_search": self.deep_search
            }
        }

# ============================================================
# B) HARDENING & SANITY
# ============================================================

@dataclass
class HardeningConfig:
    eps_norm: float = 1e-12
    eps_dom: float = 1e-12
    eps_div: float = 1e-12
    
    fuse_window: int = 32
    tau_growth: float = 0.35
    tau_cond_proxy: float = 1e10
    tau_sanitize_frac: float = 0.02
    
    stagnation_window: int = 64
    stagnation_tol: float = 1e-9

@dataclass
class SanityStats:
    nonfinite_hits: int = 0
    clamp_count: int = 0
    
def sanitize_array(x: np.ndarray, stats: Optional[SanityStats] = None) -> np.ndarray:
    m = ~np.isfinite(x)
    if m.any():
        if stats: stats.nonfinite_hits += int(m.sum())
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return x

# ============================================================
# C) PRECISION & EXACT MATH
# ============================================================

LIM = 2**62

def _to_object(arr: np.ndarray) -> List[List[int]]:
    return [[int(x) for x in row] for row in arr]

def safe_int64_basis(B: np.ndarray) -> Tuple[Any, bool]:
    """
    Returns (basis, is_object). 
    If basis contains values > LIM, converts to Python list of ints.
    """
    try:
        mx = int(np.max(np.abs(B)))
    except Exception:
        mx = LIM + 1 # Force object mode if complex/weird
        
    if mx > LIM:
        return _to_object(B), True
    return B.astype(np.int64), False

def escalate_to_object(B: Any, U: Any, maxabs: Optional[Any] = None) -> Tuple[Any, Any, Optional[Any]]:
    """Convert basis, transform and maxabs to object/list mode."""
    if isinstance(B, list):
        return B, U, maxabs
    B_new = _to_object(B)
    U_new = _to_object(U)
    mx_new = None
    if maxabs is not None:
        mx_new = [int(x) for x in maxabs]
    return B_new, U_new, mx_new

def _check_overflow_risk(maxabs_i: int, k: int, maxabs_j: int) -> bool:
    """True if row_i += k * row_j risks overflow in int64."""
    return maxabs_i + abs(int(k)) * maxabs_j > LIM

def norm2_exact(v: Any) -> int:
    """L2 norm squared using exact integer arithmetic."""
    if isinstance(v, np.ndarray) and v.dtype != object:
        return int(np.dot(v, v))
    s = 0
    for x in v:
        s += int(x) * int(x)
    return s

def dot_exact(v1: Any, v2: Any) -> int:
    """Dot product using exact integer arithmetic."""
    if isinstance(v1, np.ndarray) and v1.dtype != object:
        return int(np.dot(v1, v2))
    s = 0
    for x, y in zip(v1, v2):
        s += int(x) * int(y)
    return s

def _maxabs_row(B: Any, i: int) -> int:
    mx = 0
    for x in B[i]:
        a = abs(int(x))
        if a > mx: mx = a
    return mx

def eye_like(n: int, B_sample: Any) -> Any:
    """Identity matrix in same format as B (numpy or list of lists)."""
    if isinstance(B_sample, np.ndarray):
        return np.eye(n, dtype=B_sample.dtype)
    return [[1 if i == j else 0 for j in range(n)] for i in range(n)]
