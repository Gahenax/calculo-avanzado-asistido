#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OPTIMA_CORE_SINGLEFILE.py
========================
Core "ALL GREEN" (single-file) for Lattice Warfare:

Included (all contracts stable, no semantic overwrite):
A) LLL baseline with unimodular tracking (B = U @ basis)
B) Global Policy Solver (attention over full mu) + Deep Swap (non-adjacent insert move)
C) Random unimodular pre-mix primitive
D) Orchestrator-friendly black_box_solver(basis, **kwargs) returning exact coeffs c s.t. v = c @ basis

Notes:
- No vectors are returned without exact coefficients.
- Deep swaps are pure permutations (unimodular) applied to both B and U.
- Gram-Schmidt is recomputed globally after each action (stable, slower, honest).
"""

from __future__ import annotations
import numpy as np
from typing import Tuple, Optional, Any

DTYPE_INT = np.int64
DTYPE_FLOAT = np.float64


# ============================================================
# A) LLL BASELINE (LAZY UPDATES + U TRACKING)
# ============================================================

def gram_schmidt(B: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Full GS (O(n^3)). Used at init and after swaps."""
    n = B.shape[0]
    Bf = B.astype(DTYPE_FLOAT)
    mu = np.zeros((n, n), dtype=DTYPE_FLOAT)
    Bstar = np.zeros_like(Bf)
    Bstar_norm = np.zeros(n, dtype=DTYPE_FLOAT)
    eps = 1e-12

    for i in range(n):
        v = Bf[i].copy()
        for j in range(i):
            denom = Bstar_norm[j]
            if denom > eps:
                mu[i, j] = (Bf[i] @ Bstar[j]) / denom
                v -= mu[i, j] * Bstar[j]
            else:
                mu[i, j] = 0.0
        Bstar[i] = v
        sq = float(v @ v)
        Bstar_norm[i] = sq if sq > eps else sq
    return mu, Bstar, Bstar_norm


def gs_update_row_k(
    B: np.ndarray,
    mu: np.ndarray,
    Bstar: np.ndarray,
    Bstar_norm: np.ndarray,
    k: int
) -> None:
    """Recompute only row k of GS (vectorized)."""
    eps = 1e-12
    B_vec = B[k].astype(DTYPE_FLOAT)

    if k == 0:
        Bstar[0] = B_vec
        Bstar_norm[0] = float(B_vec @ B_vec)
        return

    denom = np.maximum(Bstar_norm[:k], eps)
    mu_row = (B_vec @ Bstar[:k].T) / denom
    mu[k, :k] = mu_row

    v = B_vec - mu_row @ Bstar[:k]
    Bstar[k] = v
    Bstar_norm[k] = float(v @ v)


def lll_reduce(
    basis_int: np.ndarray,
    delta: float = 0.99,
    max_iter: Optional[int] = None,
    max_iter_factor: int = 200
) -> Tuple[np.ndarray, np.ndarray, int, bool]:
    """
    LLL with lazy GS updates on size-reduction; full GS after swaps.
    Returns:
      B: reduced basis (rows)
      U: unimodular matrix so that B = U @ basis
      iters: loop iterations
      stopped: True if hit max_iter
    """
    B = basis_int.astype(DTYPE_INT).copy()
    n = B.shape[0]
    U = np.eye(n, dtype=DTYPE_INT)

    if max_iter is None:
        max_iter = n * n * int(max_iter_factor)

    mu, Bstar, Bstar_norm = gram_schmidt(B)

    k = 1
    iters = 0
    stopped = False

    while k < n:
        iters += 1
        if iters > max_iter:
            stopped = True
            break

        # Size reduction (lazy update mu algebraically, then resync geometry on row k)
        for j in range(k - 1, -1, -1):
            if abs(mu[k, j]) > 0.5000000001:
                q = int(np.rint(mu[k, j]))
                if q != 0:
                    B[k] -= q * B[j]
                    U[k] -= q * U[j]

                    mu[k, j] -= q
                    for i in range(j):
                        mu[k, i] -= q * mu[j, i]

        gs_update_row_k(B, mu, Bstar, Bstar_norm, k)

        lhs = Bstar_norm[k]
        rhs = (delta - mu[k, k - 1] ** 2) * Bstar_norm[k - 1]

        if lhs >= rhs:
            k += 1
        else:
            B[[k, k - 1]] = B[[k - 1, k]]
            U[[k, k - 1]] = U[[k - 1, k]]

            mu, Bstar, Bstar_norm = gram_schmidt(B)
            k = max(k - 1, 1)

    return B, U, iters, stopped


# ============================================================
# B) GLOBAL POLICY SOLVER + DEEP SWAP (ALL GREEN)
# ============================================================

def deep_insert_rows(B: np.ndarray, U: np.ndarray, src: int, dst: int) -> None:
    """
    Move row src to position dst (insert), shifting the block in between.
    This is equivalent to a sequence of adjacent swaps, hence unimodular.
    Applies the same move to U to preserve: B = U @ basis.
    """
    if src == dst:
        return

    if src < dst:
        rowB = B[src].copy()
        rowU = U[src].copy()
        B[src:dst] = B[src + 1:dst + 1]
        U[src:dst] = U[src + 1:dst + 1]
        B[dst] = rowB
        U[dst] = rowU
    else:
        rowB = B[src].copy()
        rowU = U[src].copy()
        B[dst + 1:src + 1] = B[dst:src]
        U[dst + 1:src + 1] = U[dst:src]
        B[dst] = rowB
        U[dst] = rowU


def pick_deep_insert(
    mu: np.ndarray,
    Bstar_norm: np.ndarray,
    delta: float,
    max_jump: int = 8
) -> Tuple[int, int, float]:
    """
    Choose a deep insert move (src -> dst) when no size-reductions remain.
    Heuristic:
      - src: row with largest conflict max_j<i |mu[i,j]|
      - dst: move src upward up to max_jump to reduce disorder
      - gain: conflict[src] * (Bstar_norm[src] - Bstar_norm[dst])

    Returns (src, dst, gain). If no move, returns (-1,-1,0).
    """
    n = mu.shape[0]
    mu_abs = np.abs(mu)

    conflict = np.zeros(n, dtype=DTYPE_FLOAT)
    for i in range(1, n):
        conflict[i] = float(np.max(mu_abs[i, :i]))

    src = int(np.argmax(conflict))
    if conflict[src] <= 0.5000001:
        return -1, -1, 0.0

    best_gain = 0.0
    best_dst = -1

    lo = max(0, src - max_jump)
    for dst in range(src - 1, lo - 1, -1):
        gain = float(conflict[src] * (Bstar_norm[src] - Bstar_norm[dst]))
        if gain > best_gain:
            best_gain = gain
            best_dst = dst

    if best_dst == -1:
        return -1, -1, 0.0
    return src, best_dst, best_gain


def global_policy_solver_deepswap(
    basis: np.ndarray,
    delta: float = 0.99,
    max_actions_factor: int = 20,
    max_jump: int = 8
) -> np.ndarray:
    """
    Global Policy Solver with Deep Insert (non-adjacent swap equivalent).

    Hybrid strategy:
    1) Sequential size reduction (all rows, bounded mu)
    2) Adjacent Lovasz swap (worst violation)
    3) Deep insert move (break ties / reorder globally)

    Returns:
      coeffs c (int64) such that v = c @ basis is the best row found.
    """
    B = basis.astype(DTYPE_INT).copy()
    n = B.shape[0]
    U = np.eye(n, dtype=DTYPE_INT)

    max_actions = n * n * int(max_actions_factor)
    actions = 0

    while actions < max_actions:
        mu, Bstar, Bstar_norm = gram_schmidt(B)

        # 1) Sequential size reduction (all rows, prevents mu overflow)
        did_reduce = False
        for i in range(1, n):
            for j in range(i - 1, -1, -1):
                if abs(mu[i, j]) > 0.5:
                    q = int(round(mu[i, j]))
                    if q != 0:
                        B[i] -= q * B[j]
                        U[i] -= q * U[j]
                        for ll in range(j):
                            mu[i, ll] -= q * mu[j, ll]
                        mu[i, j] -= q
                        actions += 1
                        did_reduce = True

        # Recompute GS after batch size reduction
        if did_reduce:
            mu, Bstar, Bstar_norm = gram_schmidt(B)

        # 2) Adjacent Lovasz swap (worst violation)
        best_violation = 0.0
        swap_k = -1
        for k in range(1, n):
            lhs = Bstar_norm[k] + mu[k, k - 1] ** 2 * Bstar_norm[k - 1]
            rhs = delta * Bstar_norm[k - 1]
            if lhs < rhs:
                violation = float(rhs - lhs)
                if violation > best_violation:
                    best_violation = violation
                    swap_k = k

        if swap_k != -1:
            B[[swap_k, swap_k - 1]] = B[[swap_k - 1, swap_k]]
            U[[swap_k, swap_k - 1]] = U[[swap_k - 1, swap_k]]
            actions += 1
            continue

        # 3) Deep insert move (break ties / reorder globally)
        src, dst, gain = pick_deep_insert(mu, Bstar_norm, delta=delta,
                                          max_jump=max_jump)
        if dst != -1 and gain > 0.0:
            deep_insert_rows(B, U, src, dst)
            actions += 1
            continue

        # Stable state
        break

    # Extract best row
    norms = np.linalg.norm(B.astype(DTYPE_FLOAT), axis=1)
    best_idx = int(np.argmin(norms))
    return U[best_idx].copy()


# ============================================================
# C) UNIMODULAR PRE-MIX PRIMITIVE (PURE)
# ============================================================

def random_unimodular_mix_U(
    n: int,
    strength: int = 2,
    rng: Optional[np.random.Generator] = None
) -> np.ndarray:
    """
    Generate a unimodular U close to identity via elementary row ops:
      U[i] += k * U[j], k in {-1, +1}
    """
    rng = rng or np.random.default_rng()
    U = np.eye(n, dtype=DTYPE_INT)
    for _ in range(n * int(strength)):
        i, j = rng.integers(0, n, size=2)
        if i != j:
            k = int(rng.choice([-1, 1]))
            U[i] += k * U[j]
    return U


# ============================================================
# D) ORCHESTRATOR-FRIENDLY BLACKBOX
# ============================================================

def black_box_solver(basis: np.ndarray, **kwargs: Any) -> np.ndarray:
    """
    Wrapper compatible with SVP Warfare Suite.
    Returns exact integer coeffs c such that v = c @ basis.

    Modes:
      mode="global_deepswap" (default): global_policy_solver_deepswap
      mode="lll": best row after LLL baseline (exact)
      mode="mix_lll": random unimodular pre-mix + LLL, repeats within budget

    kwargs:
      delta: float (default 0.99)
      mode: str
      time_budget: float seconds (for mix_lll)
      mix_strength: int
      max_actions_factor: int (global)
      max_jump: int (global)
    """
    import time as _time

    delta = float(kwargs.get("delta", 0.99))
    mode = str(kwargs.get("mode", "global_deepswap"))

    n = basis.shape[0]

    if mode == "lll":
        B, U, _, _ = lll_reduce(basis, delta=delta)
        norms = np.linalg.norm(B.astype(DTYPE_FLOAT), axis=1)
        return U[int(np.argmin(norms))].copy()

    if mode == "mix_lll":
        time_budget = float(kwargs.get("time_budget", 2.0))
        mix_strength = int(kwargs.get("mix_strength", 4))
        rng = np.random.default_rng()

        # baseline
        B0, U0, _, _ = lll_reduce(basis, delta=delta)
        norms0 = np.linalg.norm(B0.astype(DTYPE_FLOAT), axis=1)
        idx0 = int(np.argmin(norms0))
        best_norm = float(norms0[idx0])
        best_coeffs = U0[idx0].copy()

        t0 = _time.time()
        while (_time.time() - t0) < time_budget:
            U_mix = random_unimodular_mix_U(n, strength=mix_strength, rng=rng)
            B_mix = U_mix @ basis
            B1, U1, _, _ = lll_reduce(B_mix, delta=delta)
            norms1 = np.linalg.norm(B1.astype(DTYPE_FLOAT), axis=1)
            idx1 = int(np.argmin(norms1))
            nrm = float(norms1[idx1])
            if nrm < best_norm - 1e-12:
                U_total = U1 @ U_mix
                best_norm = nrm
                best_coeffs = U_total[idx1].copy()

        return best_coeffs

    # default: global_deepswap
    max_actions_factor = int(kwargs.get("max_actions_factor", 20))
    max_jump = int(kwargs.get("max_jump", 8))
    return global_policy_solver_deepswap(
        basis=basis,
        delta=delta,
        max_actions_factor=max_actions_factor,
        max_jump=max_jump
    )


# ============================================================
# Minimal self-test
# ============================================================

if __name__ == "__main__":
    rng = np.random.default_rng(0)
    n = 20
    basis = rng.integers(-20, 21, size=(n, n), dtype=DTYPE_INT)

    c_lll = black_box_solver(basis, mode="lll", delta=0.99)
    v_lll = c_lll @ basis
    n_lll = float(np.linalg.norm(v_lll.astype(DTYPE_FLOAT)))

    c_bb = black_box_solver(basis, mode="global_deepswap", delta=0.99, max_jump=8)
    v_bb = c_bb @ basis
    n_bb = float(np.linalg.norm(v_bb.astype(DTYPE_FLOAT)))

    c_mix = black_box_solver(basis, mode="mix_lll", delta=0.99, time_budget=2.0)
    v_mix = c_mix @ basis
    n_mix = float(np.linalg.norm(v_mix.astype(DTYPE_FLOAT)))

    print(f"LLL         norm: {n_lll:.6f}")
    print(f"DeepSwap    norm: {n_bb:.6f}")
    print(f"MixLLL      norm: {n_mix:.6f}")
    best = min(n_lll, n_bb, n_mix)
    print(f"Best:            {best:.6f}")
    print("ALL GREEN" if n_bb <= n_lll + 1e-12 else f"DeepSwap WORSE by {(n_bb/n_lll - 1)*100:.2f}%")
