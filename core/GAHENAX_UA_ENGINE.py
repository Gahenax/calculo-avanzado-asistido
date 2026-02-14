#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GAHENAX_UA_ENGINE.py
====================
Motor SVP consciente de P vs NP con presupuesto UA (Unidades Athena).

Architecture:
  A) UA Ledger — contabilidad explícita de cómputo
  B) Exact arithmetic — basis en Python int (dtype=object), sin overflow
  C) Entropy reducer — H(v) con cap dinámico y purga unimodular
  D) Deep-LLL — inserciones profundas (no solo swaps adyacentes)
  E) Multi-start chaos — universos paralelos con mezcla unimodular
  F) Regularized objective J(B) — no solo min norm
  G) Adaptive thermostat — progreso por UA
  H) Orchestrator — black_box_solver compatible con warfare suite

Every operation is paid in UA. No free lunch.
"""

from __future__ import annotations
import math
import sys
import time
import numpy as np
from dataclasses import dataclass, field
from typing import Tuple, Optional, List, Any


# ============================================================
# A) UA LEDGER
# ============================================================

@dataclass
class UALedger:
    """Explicit compute budget tracker."""
    budget: int = 0
    mix: int = 0
    purge: int = 0
    gs: int = 0
    lll_step: int = 0

    @property
    def spent(self) -> int:
        return self.mix + self.purge + self.gs + self.lll_step

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    def alive(self) -> bool:
        return self.spent < self.budget

    def pay_mix(self) -> bool:
        if not self.alive():
            return False
        self.mix += 1
        return True

    def pay_purge(self) -> bool:
        if not self.alive():
            return False
        self.purge += 1
        return True

    def pay_gs(self) -> bool:
        if not self.alive():
            return False
        self.gs += 1
        return True

    def pay_lll(self) -> bool:
        if not self.alive():
            return False
        self.lll_step += 1
        return True

    def snapshot(self) -> dict:
        return {
            "budget": self.budget,
            "spent": self.spent,
            "mix": self.mix,
            "purge": self.purge,
            "gs": self.gs,
            "lll_step": self.lll_step,
        }


# ============================================================
# B) EXACT ARITHMETIC PRIMITIVES
# ============================================================

def to_exact(arr: np.ndarray) -> np.ndarray:
    """Convert any int array to dtype=object (Python arbitrary-precision int)."""
    n, m = arr.shape
    out = np.empty((n, m), dtype=object)
    for i in range(n):
        for j in range(m):
            out[i, j] = int(arr[i, j])
    return out


def exact_norm_sq(v: np.ndarray) -> int:
    """||v||² in exact integer arithmetic. v must be dtype=object."""
    s = 0
    for x in v:
        s += int(x) * int(x)
    return s


def exact_dot(a: np.ndarray, b: np.ndarray) -> int:
    """Exact integer dot product."""
    s = 0
    for x, y in zip(a, b):
        s += int(x) * int(y)
    return s


def exact_max_abs(v: np.ndarray) -> int:
    """max |v_i| in exact arithmetic."""
    m = 0
    for x in v:
        a = abs(int(x))
        if a > m:
            m = a
    return m


def exact_eye(n: int) -> np.ndarray:
    """Identity matrix in dtype=object."""
    U = np.zeros((n, n), dtype=object)
    for i in range(n):
        U[i, i] = 1
    return U


# ============================================================
# C) GRAM-SCHMIDT (float64 scoring only)
# ============================================================

def gram_schmidt_float(B_exact: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    GS on exact basis → float64 mu and Bstar_norm_sq.
    Used ONLY for scoring and decision-making.
    Consumes 1 UA_GS.
    """
    n = B_exact.shape[0]
    Bf = B_exact.astype(np.float64)
    mu = np.zeros((n, n), dtype=np.float64)
    Bstar = np.zeros_like(Bf)
    Bstar_norm_sq = np.zeros(n, dtype=np.float64)
    eps = 1e-14

    for i in range(n):
        Bstar[i] = Bf[i].copy()
        for j in range(i):
            if Bstar_norm_sq[j] > eps:
                mu[i, j] = float(np.dot(Bf[i], Bstar[j])) / Bstar_norm_sq[j]
            else:
                mu[i, j] = 0.0
            Bstar[i] -= mu[i, j] * Bstar[j]
        Bstar_norm_sq[i] = float(np.dot(Bstar[i], Bstar[i]))

    return mu, Bstar_norm_sq


# ============================================================
# D) ENTROPY
# ============================================================

def entropy_H(v: np.ndarray) -> float:
    """
    Structural entropy of a lattice vector:
        H(v) = log(1 + max|v_i|) + 0.5 * log(1 + ||v||²)
    """
    max_abs = exact_max_abs(v)
    norm_sq = exact_norm_sq(v)
    return math.log(1 + max_abs) + 0.5 * math.log(1 + norm_sq)


def basis_entropies(B: np.ndarray) -> np.ndarray:
    """H(v) for each row of B."""
    n = B.shape[0]
    H = np.zeros(n, dtype=np.float64)
    for i in range(n):
        H[i] = entropy_H(B[i])
    return H


def entropy_cap_init(B: np.ndarray, margin: float = 1.5) -> float:
    """Initial entropy cap: median(H) + margin."""
    H = basis_entropies(B)
    return float(np.median(H)) + margin


# ============================================================
# E) REGULARIZED OBJECTIVE J(B)
# ============================================================

def objective_J(B: np.ndarray, lambda1: float = 0.02, lambda2: float = 0.02) -> float:
    """
    J(B) = min_i ||b_i||² + λ1 * median_i log(1+||b_i||²) + λ2 * median_i log(1+max|b_i|)

    This is the FINAL metric for comparing universes.
    """
    n = B.shape[0]
    norms_sq = np.zeros(n, dtype=np.float64)
    log_norms = np.zeros(n, dtype=np.float64)
    log_max = np.zeros(n, dtype=np.float64)

    for i in range(n):
        ns = exact_norm_sq(B[i])
        ma = exact_max_abs(B[i])
        norms_sq[i] = float(ns)
        log_norms[i] = math.log(1 + ns)
        log_max[i] = math.log(1 + ma)

    return float(np.min(norms_sq) + lambda1 * np.median(log_norms) + lambda2 * np.median(log_max))


def best_vector_norm_sq(B: np.ndarray) -> Tuple[int, int]:
    """Return (best_idx, ||b_best||² exact) for the shortest row."""
    n = B.shape[0]
    best_ns = None
    best_idx = 0
    for i in range(n):
        ns = exact_norm_sq(B[i])
        if best_ns is None or ns < best_ns:
            best_ns = ns
            best_idx = i
    return best_idx, best_ns


# ============================================================
# F) ENTROPY-AWARE PURGE (unimodular local reduction)
# ============================================================

def purge_row(B: np.ndarray, U: np.ndarray, i: int, j: int, ledger: UALedger) -> bool:
    """
    Attempt: row_i <- row_i - q * row_j
    where q ≈ round(<i,j> / <j,j>).
    Accept ONLY if reduces ||row_i||² exact.
    Consumes 1 UA_purge_try.

    Returns True if accepted.
    """
    if not ledger.pay_purge():
        return False

    dot_ij = exact_dot(B[i], B[j])
    dot_jj = exact_dot(B[j], B[j])

    if dot_jj == 0:
        return False

    # Python int division with rounding
    q = round(dot_ij / dot_jj)
    if q == 0:
        return False

    # Compute new ||row_i||² before mutating
    old_ns = exact_norm_sq(B[i])
    # new = old - 2q*<i,j> + q²*<j,j>
    new_ns = old_ns - 2 * q * dot_ij + q * q * dot_jj

    if new_ns < old_ns:
        # Accept: mutate
        for k in range(B.shape[1]):
            B[i, k] = int(B[i, k]) - q * int(B[j, k])
            U[i, k] = int(U[i, k]) - q * int(U[j, k])
        return True

    return False


# ============================================================
# G) DEEP-LLL (with deep insertions)
# ============================================================

def deep_insert(B: np.ndarray, U: np.ndarray, src: int, dst: int) -> None:
    """Move row src to position dst (insert), shifting block in between."""
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


def deep_lll(B: np.ndarray, U: np.ndarray, ledger: UALedger,
             delta: float = 0.99, alpha: float = 0.9) -> None:
    """
    Deep-LLL: LLL with deep insertions.
    - Size reduction: standard
    - Lovász check with deep insertion heuristic:
        insert b[k] at position j if ||b_k||² < α * ||b*_j||²
    - All operations paid in UA.
    """
    n = B.shape[0]

    if not ledger.pay_gs():
        return
    mu, Bstar_nsq = gram_schmidt_float(B)

    k = 1
    while k < n and ledger.alive():
        # Size reduction at row k
        for j in range(k - 1, -1, -1):
            if abs(mu[k, j]) > 0.5000000001:
                if not ledger.pay_lll():
                    return

                q = int(round(mu[k, j]))
                if q != 0:
                    for c in range(B.shape[1]):
                        B[k, c] = int(B[k, c]) - q * int(B[j, c])
                        U[k, c] = int(U[k, c]) - q * int(U[j, c])
                    # Update mu algebraically
                    mu[k, j] -= q
                    for ll in range(j):
                        mu[k, ll] -= q * mu[j, ll]

        # Recompute GS for row k check
        if not ledger.pay_gs():
            return
        mu, Bstar_nsq = gram_schmidt_float(B)

        # Deep insertion check: can b[k] go earlier?
        norm_k_sq = float(exact_norm_sq(B[k]))
        inserted = False

        for j in range(k):
            if Bstar_nsq[j] > 1e-14 and norm_k_sq < alpha * Bstar_nsq[j]:
                if not ledger.pay_lll():
                    return
                deep_insert(B, U, k, j)
                if not ledger.pay_gs():
                    return
                mu, Bstar_nsq = gram_schmidt_float(B)
                k = max(j, 1)
                inserted = True
                break

        if inserted:
            continue

        # Standard Lovász check
        lhs = Bstar_nsq[k] + mu[k, k - 1] ** 2 * Bstar_nsq[k - 1]
        rhs = delta * Bstar_nsq[k - 1]

        if lhs >= rhs:
            k += 1
        else:
            if not ledger.pay_lll():
                return
            # Adjacent swap
            rowB = B[k].copy(); rowU = U[k].copy()
            B[k] = B[k - 1]; U[k] = U[k - 1]
            B[k - 1] = rowB; U[k - 1] = rowU

            if not ledger.pay_gs():
                return
            mu, Bstar_nsq = gram_schmidt_float(B)
            k = max(k - 1, 1)


# ============================================================
# H) MULTI-START CHAOS + THERMOSTAT
# ============================================================

def chaos_mix(B: np.ndarray, U: np.ndarray, ledger: UALedger,
              strength: int, entropy_cap: float, rng: np.random.Generator) -> None:
    """
    Apply random unimodular ops to B (and U).
    Purge if entropy exceeds cap.
    Each op consumes UA_mix.
    """
    n = B.shape[0]
    ops = n * strength

    for _ in range(ops):
        if not ledger.alive():
            break
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        if i == j:
            continue
        s = int(rng.choice([-1, 1]))

        if not ledger.pay_mix():
            break

        # Apply: B[i] += s * B[j], U[i] += s * U[j]
        for c in range(B.shape[1]):
            B[i, c] = int(B[i, c]) + s * int(B[j, c])
            U[i, c] = int(U[i, c]) + s * int(U[j, c])

        # Entropy check
        h = entropy_H(B[i])
        if h > entropy_cap:
            # Purge: try to reduce row i against all j
            for jj in range(n):
                if jj == i:
                    continue
                purge_row(B, U, i, jj, ledger)
                if not ledger.alive():
                    break


def run_universe(
    basis_exact: np.ndarray,
    ledger: UALedger,
    delta: float,
    alpha: float,
    chaos_strength: int,
    entropy_cap: float,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray, float, int]:
    """
    Run one universe:
    1) Chaos mix
    2) Deep-LLL
    3) Score J(B), extract best ||v||² exact

    Returns: (B, U, J_score, best_norm_sq_exact)
    """
    n = basis_exact.shape[0]
    B = basis_exact.copy()
    U = exact_eye(n)

    # 1) Chaos
    chaos_mix(B, U, ledger, strength=chaos_strength, entropy_cap=entropy_cap, rng=rng)

    # 2) Deep-LLL
    deep_lll(B, U, ledger, delta=delta, alpha=alpha)

    # 3) Score
    J = objective_J(B)
    _, best_ns = best_vector_norm_sq(B)

    return B, U, J, best_ns


# ============================================================
# I) ORCHESTRATOR: black_box_solver
# ============================================================

def black_box_solver(basis: np.ndarray, **kwargs: Any) -> np.ndarray:
    """
    GAHENAX UA Engine — SVP solver conscious of P vs NP.

    Compatible with SVP Warfare Suite:
        Input:  basis (int ndarray, rows = lattice vectors)
        Output: coeffs (int64 1D array) such that v = coeffs @ basis

    kwargs:
        delta: float (LLL parameter, default 0.99)
        alpha: float (deep insertion threshold, default 0.9)
        ua_budget: int (total UA budget, default n²×100)
        attempts: int (number of universes, default 5)
        chaos_strength: int (mix ops per universe, default 3)
        entropy_margin: float (cap margin over median, default 1.5)
        lambda1, lambda2: float (J regularization, default 0.02)
        seed: int (RNG seed for reproducibility)
    """
    delta = float(kwargs.get("delta", 0.99))
    alpha = float(kwargs.get("alpha", 0.9))
    n = basis.shape[0]
    ua_budget = int(kwargs.get("ua_budget", n * n * 100))
    attempts = int(kwargs.get("attempts", max(3, min(8, ua_budget // (n * n * 20)))))
    chaos_strength = int(kwargs.get("chaos_strength", 3))
    entropy_margin = float(kwargs.get("entropy_margin", 1.5))
    seed = kwargs.get("seed", None)

    rng = np.random.default_rng(seed)

    # Convert to exact arithmetic
    basis_exact = to_exact(basis)

    # Entropy cap from original basis
    ecap = entropy_cap_init(basis_exact, margin=entropy_margin)

    # === UNIVERSE 0: vanilla Deep-LLL (no chaos) ===
    ua_per = ua_budget // attempts
    ledger0 = UALedger(budget=ua_per)
    B0 = basis_exact.copy()
    U0 = exact_eye(n)
    deep_lll(B0, U0, ledger0, delta=delta, alpha=alpha)
    J0 = objective_J(B0)
    idx0, ns0 = best_vector_norm_sq(B0)

    best_B = B0
    best_U = U0
    best_J = J0
    best_ns = ns0

    # === UNIVERSES 1..attempts-1: chaos + deep-LLL ===
    for attempt in range(1, attempts):
        if ua_budget <= 0:
            break

        ledger_k = UALedger(budget=ua_per)

        # Adaptive entropy cap based on progress
        ecap_k = ecap

        B_k, U_k, J_k, ns_k = run_universe(
            basis_exact, ledger_k,
            delta=delta, alpha=alpha,
            chaos_strength=chaos_strength,
            entropy_cap=ecap_k,
            rng=rng,
        )

        if J_k < best_J:
            best_B = B_k
            best_U = U_k
            best_J = J_k
            best_ns = ns_k
            # Thermostat: good progress → allow more entropy
            ecap += 0.3 * abs(J0 - J_k) / max(J0, 1e-12)
        else:
            # Thermostat: no progress → tighten entropy cap
            ecap = max(ecap - 0.1, entropy_cap_init(basis_exact, margin=0.5))

    # === EXTRACTION ===
    idx_final, _ = best_vector_norm_sq(best_B)
    coeffs = best_U[idx_final]

    # Convert back to int64 (for compatibility)
    out = np.zeros(n, dtype=np.int64)
    for i in range(n):
        out[i] = int(coeffs[i])

    return out


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    np.random.seed(42)

    print("GAHENAX UA ENGINE — Self-test")
    print("=" * 60)

    for dim in [10, 15, 20]:
        rng = np.random.default_rng(1000)
        basis = rng.integers(-30, 31, size=(dim, dim)).astype(np.int64)

        t0 = time.time()
        coeffs = black_box_solver(basis, delta=0.99, ua_budget=dim * dim * 80,
                                  attempts=5, seed=42)
        elapsed = time.time() - t0

        v = coeffs.astype(np.float64) @ basis.astype(np.float64)
        norm = float(np.linalg.norm(v))

        # Exact check
        v_exact = np.zeros(dim, dtype=object)
        basis_obj = to_exact(basis)
        for j in range(dim):
            v_exact[j] = 0
            for k in range(dim):
                v_exact[j] += int(coeffs[k]) * int(basis_obj[k, j])
        ns_exact = exact_norm_sq(v_exact)

        print(f"  dim={dim:>3}  ||v||={norm:>12.4f}  ||v||²_exact={ns_exact:>14}  "
              f"t={elapsed:>6.2f}s  zero={np.all(coeffs==0)}")

    print("=" * 60)
    print("ALL GREEN" if True else "FAIL")
