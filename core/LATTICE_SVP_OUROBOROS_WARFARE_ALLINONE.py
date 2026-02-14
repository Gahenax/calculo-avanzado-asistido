#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LATTICE_SVP_OUROBOROS_WARFARE_ALLINONE.py
# ==========================================
# Ouroboros SVP Warfare Suite
# Single-file, deterministic, reproducible, no-hype.
#
# Usage:
#   python LATTICE_SVP_OUROBOROS_WARFARE_ALLINONE.py
#   python LATTICE_SVP_OUROBOROS_WARFARE_ALLINONE.py --dims 40,50 --samples 3
#   python LATTICE_SVP_OUROBOROS_WARFARE_ALLINONE.py --dims 60,70,80 --samples 10 --out results.csv
#
# Dependencies: numpy (only external), Python >= 3.8
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from dataclasses import dataclass, fields, asdict
from typing import List, Tuple, Optional

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# A) CONFIG
# ============================================================================

DEFAULT_DIMENSIONS = [40, 50, 60, 70, 80]
DEFAULT_SAMPLES_PER_DIM = 5
DEFAULT_OUTPUT_CSV = "lattice_warfare_results.csv"
DEFAULT_LLL_DELTA = 0.99
DEFAULT_MAX_ITER_FACTOR = 50
DEFAULT_MIX_FACTOR = 8
DEFAULT_MIX_K_ABS = 3
DEFAULT_SEED0 = 1000
DEFAULT_SEED_STEP = 17

INT64_EXTREME = np.int64(2**62)


# ============================================================================
# B) CORE: ORACLE
# ============================================================================

@dataclass
class LatticeChallenge:
    basis: np.ndarray        # int64, shape (n, n), rows = base vectors
    dimension: int
    log_determinant: float
    gaussian_heuristic: float
    seed: int


class LatticeOracle:
    """Generates integer-lattice SVP challenges and evaluates solutions."""

    def __init__(self, mix_factor: int = DEFAULT_MIX_FACTOR,
                 mix_k_abs: int = DEFAULT_MIX_K_ABS):
        self.mix_factor = mix_factor
        self.mix_k_abs = mix_k_abs

    def generate_challenge(self, n: int, seed: int) -> LatticeChallenge:
        """
        Generate a deterministic integer lattice challenge.
        B = U @ D where D = diag(scales), U = product of unimodular row ops.
        """
        rng = np.random.RandomState(seed)

        # Diagonal lattice with controlled scale
        scales = np.array([1000 + 50 * i for i in range(n)], dtype=np.int64)
        D = np.diag(scales)

        # Build unimodular matrix via row operations
        U = np.eye(n, dtype=np.int64)
        n_ops = self.mix_factor * n
        for _ in range(n_ops):
            i = rng.randint(0, n)
            j = rng.randint(0, n)
            if i == j:
                continue
            k = rng.randint(-self.mix_k_abs, self.mix_k_abs + 1)
            if k == 0:
                continue
            U[i] = U[i] + k * U[j]

        # Basis = U @ D
        B = U @ D

        # Overflow-like guard: check for extreme int64 values
        if np.any(np.abs(B) > INT64_EXTREME):
            raise OverflowError(
                f"Basis contains extreme int64 values (seed={seed}, n={n}). "
                f"Reduce mix_factor or mix_k_abs."
            )

        # Lattice invariants
        log_det = float(np.sum(np.log(scales.astype(np.float64))))
        gh = self._gaussian_heuristic(n, log_det)

        return LatticeChallenge(
            basis=B,
            dimension=n,
            log_determinant=log_det,
            gaussian_heuristic=gh,
            seed=seed,
        )

    @staticmethod
    def _gaussian_heuristic(n: int, log_det: float) -> float:
        """GH = sqrt(n / (2*pi*e)) * det(L)^{1/n}."""
        log_gh = 0.5 * (math.log(n) - math.log(2.0 * math.pi * math.e))
        log_gh += log_det / n
        return math.exp(log_gh)

    def evaluate(self, challenge: LatticeChallenge,
                 coeffs: np.ndarray) -> float:
        """
        Given integer coefficients, compute ||coeffs @ basis||.
        coeffs: 1D int64 array of length n.
        Returns: Euclidean norm as float64.
        """
        coeffs = np.asarray(coeffs, dtype=np.int64).ravel()
        if coeffs.shape[0] != challenge.dimension:
            raise ValueError(
                f"coeffs length {coeffs.shape[0]} != dimension {challenge.dimension}"
            )
        if np.all(coeffs == 0):
            return float("inf")
        v = coeffs.astype(np.float64) @ challenge.basis.astype(np.float64)
        return float(np.linalg.norm(v))

    def check_success(self, challenge: LatticeChallenge, norm: float) -> bool:
        """Success if norm/GH < 1.05."""
        if challenge.gaussian_heuristic <= 0:
            return False
        return (norm / challenge.gaussian_heuristic) < 1.05


# ============================================================================
# C) METRICS
# ============================================================================

def estimate_delta0(n: int, log_det: float, norm: float) -> float:
    """
    Root Hermite factor delta_0:
      delta_0 = exp( (log(norm)/n) - (log_det / n^2) )
    """
    if norm <= 0 or n <= 0:
        return float("inf")
    return math.exp((math.log(norm) / n) - (log_det / (n * n)))


# ============================================================================
# D) LLL BASELINE WITH TRACKING (optimized incremental GS)
# ============================================================================

def gram_schmidt(B: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Classical Gram-Schmidt on rows of B (float64).
    Returns: mu (lower triangular), Bstar (orthogonalized rows), Bstar_norms_sq.
    """
    n = B.shape[0]
    Bf = B.astype(np.float64)
    mu = np.zeros((n, n), dtype=np.float64)
    Bstar = np.zeros_like(Bf)
    Bstar_norms = np.zeros(n, dtype=np.float64)

    for i in range(n):
        Bstar[i] = Bf[i].copy()
        for j in range(i):
            if Bstar_norms[j] > 1e-14:
                mu[i, j] = np.dot(Bf[i], Bstar[j]) / Bstar_norms[j]
            else:
                mu[i, j] = 0.0
            Bstar[i] -= mu[i, j] * Bstar[j]
        Bstar_norms[i] = np.dot(Bstar[i], Bstar[i])

    return mu, Bstar, Bstar_norms


def _gs_update_from(B: np.ndarray, mu: np.ndarray, Bstar: np.ndarray,
                    Bstar_norms: np.ndarray, start: int) -> None:
    """Recompute GS from row 'start' onwards (in-place)."""
    n = B.shape[0]
    Bf = B.astype(np.float64)
    for i in range(start, n):
        Bstar[i] = Bf[i].copy()
        for j in range(i):
            if Bstar_norms[j] > 1e-14:
                mu[i, j] = np.dot(Bf[i], Bstar[j]) / Bstar_norms[j]
            else:
                mu[i, j] = 0.0
            Bstar[i] -= mu[i, j] * Bstar[j]
        Bstar_norms[i] = np.dot(Bstar[i], Bstar[i])


def lll_reduce(basis_int: np.ndarray, delta: float = 0.99,
               max_iter_factor: int = 50
               ) -> Tuple[np.ndarray, np.ndarray, int, bool]:
    """
    LLL reduction with unimodular transform tracking.
    Uses incremental Gram-Schmidt updates for performance.
    Returns: (B_reduced int64, U int64, iterations, stopped_early).
    B_reduced = U @ basis_int.
    """
    n = basis_int.shape[0]
    B = basis_int.copy().astype(np.int64)
    U = np.eye(n, dtype=np.int64)
    max_iters = max(n * n * max_iter_factor, 1000)

    mu, Bstar, Bstar_norms = gram_schmidt(B)

    k = 1
    iters = 0
    stopped = False

    while k < n:
        iters += 1
        if iters > max_iters:
            stopped = True
            break

        # Size reduction
        for j in range(k - 1, -1, -1):
            if abs(mu[k, j]) > 0.5:
                q = int(round(mu[k, j]))
                B[k] -= q * B[j]
                U[k] -= q * U[j]
                # Update mu for row k
                for ll in range(j):
                    mu[k, ll] -= q * mu[j, ll]
                mu[k, j] -= q

        # Lovasz condition
        lhs = Bstar_norms[k] + mu[k, k - 1] ** 2 * Bstar_norms[k - 1]
        rhs = delta * Bstar_norms[k - 1]

        if lhs >= rhs:
            k += 1
        else:
            # Swap rows k and k-1
            B[[k, k - 1]] = B[[k - 1, k]]
            U[[k, k - 1]] = U[[k - 1, k]]
            # Incremental GS update: only recompute from k-1 onwards
            _gs_update_from(B, mu, Bstar, Bstar_norms, k - 1)
            k = max(k - 1, 1)

    return B, U, iters, stopped


def solve_challenge_with_lll(
    oracle: LatticeOracle,
    challenge: LatticeChallenge,
    delta: float = 0.99,
    max_iter_factor: int = 200,
) -> Tuple[float, np.ndarray, float, bool, int, float, int]:
    """
    Run LLL on challenge and evaluate shortest row.
    Returns: (norm, coeffs, elapsed, stopped, iters, min_row_norm, min_idx).
    """
    t0 = time.time()
    B_red, U, iters, stopped = lll_reduce(
        challenge.basis.copy(), delta=delta, max_iter_factor=max_iter_factor
    )
    elapsed = time.time() - t0

    # Find shortest row in reduced basis
    B_red_f = B_red.astype(np.float64)
    row_norms = np.array([np.linalg.norm(B_red_f[i]) for i in range(B_red.shape[0])])
    min_idx = int(np.argmin(row_norms))
    min_row_norm = float(row_norms[min_idx])

    # Coefficients for the shortest row: U[min_idx] are the integer
    # coefficients such that B_red[min_idx] = U[min_idx] @ basis_orig
    coeffs = U[min_idx].copy()

    # Oracle evaluation (recompute norm from original)
    real_norm = oracle.evaluate(challenge, coeffs)

    return real_norm, coeffs, elapsed, stopped, iters, min_row_norm, min_idx


# ============================================================================
# E) BLACKBOX SOLVER HOOK
# ============================================================================

def black_box_solver(basis: np.ndarray, **kwargs) -> np.ndarray:
    """
    BlackBox solver mount point.
    User can replace this function's internals.

    Input:  basis (int64 ndarray, rows = lattice vectors)
    Output: coeffs (int64 1D array, length n)
            such that coeffs @ basis is a short lattice vector.

    Default: runs LLL and returns shortest-row coefficients.
    """
    n = basis.shape[0]
    delta = kwargs.get("delta", 0.99)
    max_iter_factor = kwargs.get("max_iter_factor", 200)

    B_red, U, _, _ = lll_reduce(basis.copy(), delta=delta,
                                max_iter_factor=max_iter_factor)

    B_red_f = B_red.astype(np.float64)
    row_norms = [np.linalg.norm(B_red_f[i]) for i in range(n)]
    min_idx = int(np.argmin(row_norms))

    return U[min_idx].astype(np.int64)


# ============================================================================
# F) WARFARE SUITE
# ============================================================================

@dataclass
class ResultRow:
    dimension: int
    seed: int
    algorithm: str
    wall_time: float
    norm_found: float
    gh_target: float
    ratio_gh: float
    delta_0: float
    is_success: bool


def run_single_battle(
    dim: int, seed: int, oracle: LatticeOracle,
    delta: float = 0.99, max_iter_factor: int = 200,
) -> List[ResultRow]:
    """Run LLL baseline + BlackBox on a single challenge."""
    challenge = oracle.generate_challenge(dim, seed)
    rows: List[ResultRow] = []

    # --- LLL Baseline ---
    norm_lll, coeffs_lll, t_lll, stopped, iters, _, _ = solve_challenge_with_lll(
        oracle, challenge, delta=delta, max_iter_factor=max_iter_factor
    )
    ratio_lll = norm_lll / challenge.gaussian_heuristic if challenge.gaussian_heuristic > 0 else float("inf")
    d0_lll = estimate_delta0(dim, challenge.log_determinant, norm_lll)
    rows.append(ResultRow(
        dimension=dim, seed=seed, algorithm="LLL",
        wall_time=round(t_lll, 4),
        norm_found=round(norm_lll, 4),
        gh_target=round(challenge.gaussian_heuristic, 4),
        ratio_gh=round(ratio_lll, 6),
        delta_0=round(d0_lll, 6),
        is_success=oracle.check_success(challenge, norm_lll),
    ))

    # --- BlackBox Solver ---
    try:
        basis_copy = challenge.basis.copy()
        t0 = time.time()
        coeffs_bb = black_box_solver(basis_copy, delta=delta,
                                     max_iter_factor=max_iter_factor)
        t_bb = time.time() - t0

        # Guard: verify basis was not mutated
        if not np.array_equal(basis_copy, challenge.basis):
            raise RuntimeError("BlackBox mutated the basis copy (integrity violation).")

        norm_bb = oracle.evaluate(challenge, coeffs_bb)
        ratio_bb = norm_bb / challenge.gaussian_heuristic if challenge.gaussian_heuristic > 0 else float("inf")
        d0_bb = estimate_delta0(dim, challenge.log_determinant, norm_bb)

        rows.append(ResultRow(
            dimension=dim, seed=seed, algorithm="BlackBox",
            wall_time=round(t_bb, 4),
            norm_found=round(norm_bb, 4),
            gh_target=round(challenge.gaussian_heuristic, 4),
            ratio_gh=round(ratio_bb, 6),
            delta_0=round(d0_bb, 6),
            is_success=oracle.check_success(challenge, norm_bb),
        ))
    except Exception as ex:
        rows.append(ResultRow(
            dimension=dim, seed=seed, algorithm="BlackBox",
            wall_time=0.0,
            norm_found=float("inf"),
            gh_target=round(challenge.gaussian_heuristic, 4),
            ratio_gh=float("inf"),
            delta_0=float("inf"),
            is_success=False,
        ))
        print(f"  [BlackBox FAIL] dim={dim} seed={seed}: {ex}", file=sys.stderr)

    return rows


# --- CSV I/O ---

def init_csv(path: str) -> None:
    """Write CSV header."""
    fieldnames = [f.name for f in fields(ResultRow)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()


def append_csv(path: str, rows: List[ResultRow]) -> None:
    """Append result rows to CSV."""
    fieldnames = [f.name for f in fields(ResultRow)]
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in rows:
            writer.writerow(asdict(row))


# --- Summary ---

def print_summary(all_rows: List[ResultRow]) -> None:
    """Print aggregated summary table grouped by (algorithm, dimension)."""
    from collections import defaultdict

    groups = defaultdict(list)
    for r in all_rows:
        groups[(r.algorithm, r.dimension)].append(r)

    print("\n" + "=" * 90)
    print(f"{'Algorithm':<12} {'Dim':>4} {'N':>3}  "
          f"{'Mean Time':>10} {'Mean Ratio':>11} {'Mean d0':>10} "
          f"{'Success':>8} {'Best Ratio':>11}")
    print("-" * 90)

    for (algo, dim) in sorted(groups.keys()):
        rs = groups[(algo, dim)]
        n = len(rs)
        mean_t = sum(r.wall_time for r in rs) / n
        ratios = [r.ratio_gh for r in rs if r.ratio_gh < float("inf")]
        d0s = [r.delta_0 for r in rs if r.delta_0 < float("inf")]
        mean_ratio = sum(ratios) / len(ratios) if ratios else float("inf")
        mean_d0 = sum(d0s) / len(d0s) if d0s else float("inf")
        best_ratio = min(ratios) if ratios else float("inf")
        n_success = sum(1 for r in rs if r.is_success)

        print(f"{algo:<12} {dim:>4} {n:>3}  "
              f"{mean_t:>10.4f} {mean_ratio:>11.4f} {mean_d0:>10.6f} "
              f"{n_success:>3}/{n:<3}  {best_ratio:>11.4f}")

    print("=" * 90)


# ============================================================================
# G) CLI + MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Ouroboros SVP Warfare Suite - Lattice benchmark harness"
    )
    ap.add_argument("--dims", type=str, default=",".join(str(d) for d in DEFAULT_DIMENSIONS),
                    help="Comma-separated dimensions (default: 40,50,60,70,80)")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES_PER_DIM,
                    help=f"Samples per dimension (default: {DEFAULT_SAMPLES_PER_DIM})")
    ap.add_argument("--seed0", type=int, default=DEFAULT_SEED0,
                    help=f"Starting seed (default: {DEFAULT_SEED0})")
    ap.add_argument("--seed_step", type=int, default=DEFAULT_SEED_STEP,
                    help=f"Seed increment (default: {DEFAULT_SEED_STEP})")
    ap.add_argument("--delta", type=float, default=DEFAULT_LLL_DELTA,
                    help=f"LLL delta parameter (default: {DEFAULT_LLL_DELTA})")
    ap.add_argument("--max_iter_factor", type=int, default=DEFAULT_MAX_ITER_FACTOR,
                    help=f"Max iterations = n*n*factor (default: {DEFAULT_MAX_ITER_FACTOR})")
    ap.add_argument("--mix_factor", type=int, default=DEFAULT_MIX_FACTOR,
                    help=f"Unimodular mixing operations = mix_factor*n (default: {DEFAULT_MIX_FACTOR})")
    ap.add_argument("--mix_k_abs", type=int, default=DEFAULT_MIX_K_ABS,
                    help=f"Unimodular k range [-k, +k] (default: {DEFAULT_MIX_K_ABS})")
    ap.add_argument("--out", type=str, default=DEFAULT_OUTPUT_CSV,
                    help=f"Output CSV path (default: {DEFAULT_OUTPUT_CSV})")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    dims = [int(d.strip()) for d in args.dims.split(",") if d.strip()]

    oracle = LatticeOracle(mix_factor=args.mix_factor, mix_k_abs=args.mix_k_abs)

    print("=" * 70)
    print("OUROBOROS SVP WARFARE SUITE")
    print("=" * 70)
    print(f"  Dimensions:      {dims}")
    print(f"  Samples/dim:     {args.samples}")
    print(f"  Seed schedule:   start={args.seed0}, step={args.seed_step}")
    print(f"  LLL delta:       {args.delta}")
    print(f"  Max iter factor: {args.max_iter_factor}")
    print(f"  Mix factor:      {args.mix_factor}")
    print(f"  Mix k_abs:       {args.mix_k_abs}")
    print(f"  Output CSV:      {args.out}")
    print("=" * 70)

    init_csv(args.out)
    all_rows: List[ResultRow] = []

    total_battles = len(dims) * args.samples
    battle_num = 0

    t_global = time.time()

    for dim in dims:
        print(f"\n[DIM {dim}]")
        for s in range(args.samples):
            seed = args.seed0 + s * args.seed_step
            battle_num += 1

            try:
                rows = run_single_battle(
                    dim, seed, oracle,
                    delta=args.delta,
                    max_iter_factor=args.max_iter_factor,
                )
                append_csv(args.out, rows)
                all_rows.extend(rows)

                # Print brief progress
                lll_row = next((r for r in rows if r.algorithm == "LLL"), None)
                bb_row = next((r for r in rows if r.algorithm == "BlackBox"), None)
                lll_ratio = f"{lll_row.ratio_gh:.4f}" if lll_row else "N/A"
                bb_ratio = f"{bb_row.ratio_gh:.4f}" if bb_row and bb_row.ratio_gh < float("inf") else "FAIL"

                print(f"  Batalla {battle_num}/{total_battles} "
                      f"(Seed {seed})... "
                      f"LLL={lll_ratio} BB={bb_ratio} OK.")
            except OverflowError as ex:
                print(f"  Batalla {battle_num}/{total_battles} "
                      f"(Seed {seed})... OVERFLOW: {ex}")
            except Exception as ex:
                print(f"  Batalla {battle_num}/{total_battles} "
                      f"(Seed {seed})... ERROR: {ex}")

    elapsed = time.time() - t_global

    # Summary
    print_summary(all_rows)
    print(f"\nTotal time: {elapsed:.1f}s")
    print(f"CSV saved: {args.out} ({len(all_rows)} rows)")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
