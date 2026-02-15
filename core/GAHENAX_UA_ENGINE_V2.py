#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GAHENAX_UA_ENGINE_V2.py
=======================
UA Engine V2 (patched): Phase A/B scheduler, int64 fast path with overflow guard,
event-driven GS, deep insertion with prefilter, directed entropy purge (signed),
Governor Kick (skip-on-stagnation + stability knobs), Floating Budget trigger,
early abort for sterile universes, JSONL logging hooks ready.
Every operation is UA-paid. No wall-clock timeout.
"""
from __future__ import annotations
import json
import math
import sys
import time
import numpy as np
import random
from dataclasses import dataclass
from typing import Tuple, Optional, List, Any, Dict

# Local imports
from gahenax_utils import (
    UALedger, HardeningConfig, SanityStats, sanitize_array,
    LIM, safe_int64_basis, escalate_to_object, _check_overflow_risk,
    norm2_exact, dot_exact, _maxabs_row, eye_like
)
from hardening import (
    UAStats, FuseState,
    condition_proxy, find_bad_rows, zero_isolation_reset,
    fuse_should_abort, ua_refund_on_abort,
    seed_is_toxic, mark_seed_fail
)
from GAHENAX_UPGRADES import (
    OpState, StepMetrics, GearboxConfig, GearboxController, GearMode,
    ShortMemoryConfig, ShortTermActionMemory
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# D) GRAM-SCHMIDT (event-driven)
# ============================================================
def gram_schmidt_float(B: Any) -> Tuple[np.ndarray, np.ndarray]:
    """Full GS → (mu, Bstar_norm_sq). float64 only."""
    if isinstance(B, list):
        Bf = np.array(B, dtype=np.float64)
    else:
        Bf = B.astype(np.float64)
    n = Bf.shape[0]
    mu = np.zeros((n, n), dtype=np.float64)
    Bstar = np.zeros_like(Bf)
    Bsn = np.zeros(n, dtype=np.float64)
    eps = 1e-14
    for i in range(n):
        Bstar[i] = Bf[i].copy()
        for j in range(i):
            if Bsn[j] > eps:
                mu[i, j] = float(np.dot(Bf[i], Bstar[j])) / Bsn[j]
            else:
                mu[i, j] = 0.0
            Bstar[i] -= mu[i, j] * Bstar[j]
        Bsn[i] = float(np.dot(Bstar[i], Bstar[i]))
    return mu, Bsn

def _update_maxabs(maxabs_cache: Any, B: Any, i: int) -> None:
    if isinstance(maxabs_cache, list):
        maxabs_cache[i] = _maxabs_row(B, i)
    else:
        maxabs_cache[i] = _maxabs_row(B, i)

def row_add(B: Any, U: Any, i: int, j: int, s: int, is_object: bool) -> None:
    s_int = int(s)
    if is_object or isinstance(B, list):
        row_i = [int(x) for x in B[i]]
        row_j = [int(x) for x in B[j]]
        u_i = [int(x) for x in U[i]]
        u_j = [int(x) for x in U[j]]
        for c in range(len(row_i)):
            row_i[c] = row_i[c] + s_int * row_j[c]
            u_i[c] = u_i[c] + s_int * u_j[c]
        B[i] = row_i
        U[i] = u_i
    else:
        # FIX: direct addition; overflow guarded before call
        B[i] = B[i] + np.int64(s_int) * B[j]
        U[i] = U[i] + np.int64(s_int) * U[j]

def row_sub(B: Any, U: Any, i: int, j: int, q: int, is_object: bool) -> None:
    q_int = int(q)
    if is_object or isinstance(B, list):
        row_i = [int(x) for x in B[i]]
        row_j = [int(x) for x in B[j]]
        u_i = [int(x) for x in U[i]]
        u_j = [int(x) for x in U[j]]
        for c in range(len(row_i)):
            row_i[c] = row_i[c] - q_int * row_j[c]
            u_i[c] = u_i[c] - q_int * u_j[c]
        B[i] = row_i
        U[i] = u_i
    else:
        B[i] -= np.int64(q_int) * B[j]
        U[i] -= np.int64(q_int) * U[j]

# ============================================================
# E) ENTROPY (cheap proxy)
# ============================================================
def entropy_row(B: Any, i: int) -> float:
    return math.log1p(_maxabs_row(B, i))

def entropy_cap_compute(B: Any) -> float:
    n = len(B)
    H = np.array([entropy_row(B, i) for i in range(n)], dtype=np.float64)
    return float(np.median(H)) + 0.25

def _min_norm2(B: Any) -> int:
    mn = None
    for i in range(len(B)):
        v = norm2_exact(B[i])
        if v > 0 and (mn is None or v < mn):
            mn = v
    return int(mn if mn is not None else 0)

# ============================================================
# F) DIRECTED PURGE (SIGNED COEFF)
# ============================================================
def directed_purge(B: Any, U: Any, i: int,
                   maxabs_cache: Any, ledger: UALedger,
                   tries: int, is_object: bool) -> Tuple[Any, Any, Any, bool, int]:
    """
    Purge row i against all other rows. Uses signed coefficient estimate q = round(dot/norm).
    Returns (B, U, maxabs_cache, is_object, exec_count).
    """
    n = len(B)
    exec_count = 0

    for _ in range(int(tries)):
        best_j = -1
        best_mu_abs = 0.5000000001
        best_mu_signed = 0.0

        for j in range(n):
            if i == j:
                continue
            norm_j = norm2_exact(B[j])
            if norm_j <= 0:
                continue
            mu_signed = dot_exact(B[i], B[j]) / float(norm_j)
            mu_abs = abs(mu_signed)
            if mu_abs > best_mu_abs:
                best_mu_abs = mu_abs
                best_j = j
                best_mu_signed = mu_signed

        if best_j == -1:
            break
        if not ledger.pay("purge_try"):
            break

        q = int(round(best_mu_signed))
        if q == 0:
            break

        if (not is_object) and (not isinstance(B, list)):
            if _check_overflow_risk(int(maxabs_cache[i]), abs(q), int(maxabs_cache[best_j])):
                B, U, maxabs_cache = escalate_to_object(B, U, maxabs_cache)
                is_object = True

        row_sub(B, U, i, best_j, q, is_object)
        _update_maxabs(maxabs_cache, B, i)
        exec_count += 1
        ledger.purge_exec += 1

    return B, U, maxabs_cache, is_object, exec_count

# ============================================================
# G) DEEP INSERTION (with cache reorder)
# ============================================================
def deep_insert(B: Any, U: Any, maxabs_cache: Any, src: int, dst: int) -> None:
    if src == dst:
        return
    if isinstance(B, list):
        B.insert(dst, B.pop(src))
        U.insert(dst, U.pop(src))
        if isinstance(maxabs_cache, list):
            maxabs_cache.insert(dst, maxabs_cache.pop(src))
        else:
            # best effort: convert to list reorder
            tmp = [int(x) for x in maxabs_cache]
            tmp.insert(dst, tmp.pop(src))
            for k in range(len(tmp)):
                maxabs_cache[k] = tmp[k]
        return

    # NumPy reorder
    rB, rU = B[src].copy(), U[src].copy()
    rM = int(maxabs_cache[src])
    if src < dst:
        B[src:dst] = B[src + 1:dst + 1]
        U[src:dst] = U[src + 1:dst + 1]
        maxabs_cache[src:dst] = maxabs_cache[src + 1:dst + 1]
        B[dst], U[dst] = rB, rU
        maxabs_cache[dst] = rM
    else:
        B[dst + 1:src + 1] = B[dst:src]
        U[dst + 1:src + 1] = U[dst:src]
        maxabs_cache[dst + 1:src + 1] = maxabs_cache[dst:src]
        B[dst], U[dst] = rB, rU
        maxabs_cache[dst] = rM

# ============================================================
# H) DEEP-LLL (event-driven GS, prefiltered deep insert)
# ============================================================
def deep_lll_v2(B: Any, U: Any, maxabs_cache: Any,
                ledger: UALedger, is_object: bool,
                delta: float, alpha: float, block_size: int,
                k_gs: int) -> Tuple[Any, Any, Any, bool, int, str]:
    """
    Deep-LLL with event-driven GS and prefiltered deep insertions.
    Returns: (B, U, maxabs_cache, is_object, deep_insert_count, status)
    """
    n = len(B)
    if not ledger.pay("gs_full"):
        return B, U, maxabs_cache, is_object, 0, "budget"
    mu, Bsn = gram_schmidt_float(B)
    steps_since_gs = 0
    deep_count = 0
    k = 1

    norms_exact = [norm2_exact(B[i]) for i in range(n)]
    if any(x < 0 for x in norms_exact):
        return B, U, maxabs_cache, is_object, deep_count, "corruption_detected"

    last_threshold = None

    while k < n and ledger.alive():
        # Size reduction at row k
        row_was_reduced = False
        for j in range(k - 1, -1, -1):
            if abs(mu[k, j]) > 0.5000000001:
                q = int(round(mu[k, j]))
                if q != 0:
                    row_was_reduced = True

                    if (not is_object) and (not isinstance(B, list)):
                        if _check_overflow_risk(int(maxabs_cache[k]), abs(q), int(maxabs_cache[j])):
                            B, U, maxabs_cache = escalate_to_object(B, U, maxabs_cache)
                            is_object = True

                    row_sub(B, U, k, j, q, is_object)
                    _update_maxabs(maxabs_cache, B, k)
                    norms_exact[k] = norm2_exact(B[k])
                    if norms_exact[k] < 0:
                        return B, U, maxabs_cache, is_object, deep_count, "corruption_detected"

                    # Update mu lazily
                    mu[k, j] -= q
                    for ll in range(j):
                        mu[k, ll] -= q * mu[j, ll]

        if row_was_reduced:
            if not ledger.pay("lll_step"):
                return B, U, maxabs_cache, is_object, deep_count, "budget"
            steps_since_gs += 1

        # Event-driven GS refresh
        if steps_since_gs >= int(k_gs):
            if not ledger.pay("gs_full"):
                return B, U, maxabs_cache, is_object, deep_count, "budget"
            mu, Bsn = gram_schmidt_float(B)
            steps_since_gs = 0

        # Deep insertion prefilter: only if k is in lowest ~30% by norm2
        if k % 7 == 0 or last_threshold is None:
            tmp = sorted(norms_exact)
            last_threshold = tmp[max(0, int(n * 0.30) - 1)]
        threshold_30 = last_threshold
        inserted = False

        norm_k = norms_exact[k]
        if norm_k <= threshold_30:
            lo = max(0, k - int(block_size))
            for d_idx, j in enumerate(range(lo, k)):
                if d_idx % 10 == 0:
                    if not ledger.pay("deep_search"):
                        return B, U, maxabs_cache, is_object, deep_count, "budget"

                if Bsn[j] > 1e-14 and float(norm_k) < float(alpha) * float(Bsn[j]):
                    if not ledger.pay("lll_step"):
                        return B, U, maxabs_cache, is_object, deep_count, "budget"

                    deep_insert(B, U, maxabs_cache, k, j)

                    rn = norms_exact.pop(k)
                    norms_exact.insert(j, rn)

                    if not ledger.pay("gs_full"):
                        return B, U, maxabs_cache, is_object, deep_count, "budget"
                    mu, Bsn = gram_schmidt_float(B)
                    steps_since_gs = 0

                    k = max(j, 1)
                    inserted = True
                    deep_count += 1
                    break

        if inserted:
            continue

        # Lovasz / swap
        lhs = Bsn[k] + mu[k, k - 1] ** 2 * Bsn[k - 1]
        rhs = delta * Bsn[k - 1]
        if lhs >= rhs:
            k += 1
        else:
            if not ledger.pay("lll_step"):
                return B, U, maxabs_cache, is_object, deep_count, "budget"

            deep_insert(B, U, maxabs_cache, k, k - 1)
            norms_exact[k], norms_exact[k - 1] = norms_exact[k - 1], norms_exact[k]

            if not ledger.pay("gs_full"):
                return B, U, maxabs_cache, is_object, deep_count, "budget"
            mu, Bsn = gram_schmidt_float(B)
            steps_since_gs = 0
            k = max(k - 1, 1)

    return B, U, maxabs_cache, is_object, deep_count, "completed"

# ============================================================
# I) CHAOS MIX (with directed purge)
# ============================================================
def chaos_mix_v2(B: Any, U: Any, maxabs_cache: Any,
                 ledger: UALedger, is_object: bool,
                 strength: int, entropy_cap: float,
                 purge_tries: int,
                 rng: np.random.Generator) -> Tuple[Any, Any, Any, bool]:
    n = len(B)
    ops = int(n) * int(strength)
    for _ in range(ops):
        if not ledger.alive():
            break
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        if i == j:
            continue
        s = int(rng.choice([-1, 1]))
        if not ledger.pay("mix"):
            break

        if (not is_object) and (not isinstance(B, list)):
            if _check_overflow_risk(int(maxabs_cache[i]), 1, int(maxabs_cache[j])):
                B, U, maxabs_cache = escalate_to_object(B, U, maxabs_cache)
                is_object = True

        row_add(B, U, i, j, s, is_object)
        _update_maxabs(maxabs_cache, B, i)

        h = entropy_row(B, i)
        if h > float(entropy_cap) + 0.30:
            B, U, maxabs_cache, is_object, _ = directed_purge(
                B, U, i, maxabs_cache, ledger, int(purge_tries), is_object
            )

    return B, U, maxabs_cache, is_object

# ============================================================
# J) UNIVERSE RUNNER (Governor Kick included)
# ============================================================
@dataclass
class UniverseResult:
    min_norm2: int = 0
    best_idx: int = 0
    J_score: float = float("inf")
    stop_reason: str = ""
    is_object: bool = False
    deep_insert_count: int = 0
    ua_spent: int = 0
    kick_triggered: bool = False
    H_before: float = 0.0
    H_after: float = 0.0

def objective_J(B: Any, lam1: float = 0.02, lam2: float = 0.02) -> float:
    n = len(B)
    ns = np.zeros(n, dtype=np.float64)
    lm = np.zeros(n, dtype=np.float64)
    for i in range(n):
        nsi = norm2_exact(B[i])
        mai = _maxabs_row(B, i)
        ns[i] = float(max(nsi, 0))
        lm[i] = math.log1p(max(mai, 0))
    safe_ns = np.maximum(ns, 1e-12)
    return float(np.min(ns) + lam1 * np.median(np.log1p(safe_ns)) + lam2 * np.median(lm))

def run_universe(basis: np.ndarray, ledger: UALedger,
                 delta: float, alpha: float, block_size: int, k_gs: int,
                 chaos_strength: int, entropy_cap: float, purge_tries: int,
                 do_chaos: bool, rng: np.random.Generator,
                 h_config: HardeningConfig = HardeningConfig()) -> Tuple[Any, Any, UniverseResult]:

    n = basis.shape[0]
    B, is_object = safe_int64_basis(basis)
    U = eye_like(n, B)

    maxabs_cache: Any
    if isinstance(B, list):
        maxabs_cache = [_maxabs_row(B, i) for i in range(n)]
    else:
        maxabs_cache = np.array([_maxabs_row(B, i) for i in range(n)], dtype=np.int64)

    stats = SanityStats()
    result = UniverseResult(is_object=is_object)
    ua_start = ledger.spent

    # Initial metrics
    min0 = _min_norm2(B)
    H0 = sum(entropy_row(B, i) for i in range(n)) / max(1, n)
    result.H_before = float(H0)
    min_initial = min0
    current_min = min0
    
    # Gearbox and Memory
    gb_cfg = GearboxConfig(stagnation_window=3) # Small window since universes are short
    gearbox = GearboxController(gb_cfg)
    mem_cfg = ShortMemoryConfig(max_items=20)
    memory = ShortTermActionMemory(mem_cfg)
    
    step_count = 0
    while ledger.alive():
        step_count += 1
        
        # Determine mode
        shift, mode, reason = gearbox.should_shift()
        
        # 1) Decision: Chaos or LLL?
        # In MICRO mode, we always do chaos. In DRILL, we only do it if explicitly requested at start.
        run_chaos = (mode == GearMode.MICRO_EXPLORE) or (do_chaos and step_count == 1)
        
        if run_chaos:
            # Strength depends on mode
            str_now = chaos_strength if mode == GearMode.MICRO_EXPLORE else max(1, chaos_strength // 2)
            B, U, maxabs_cache, is_object = chaos_mix_v2(
                B, U, maxabs_cache, ledger, is_object,
                str_now, entropy_cap, purge_tries, rng
            )

        # 2) Deep-LLL
        # In MICRO mode, we use more aggressive GS frequency
        k_gs_now = k_gs if mode == GearMode.DRILL else max(5, k_gs // 2)
        B, U, maxabs_cache, is_object, deep_count, status = deep_lll_v2(
            B, U, maxabs_cache, ledger, is_object,
            delta=delta, alpha=alpha, block_size=block_size, k_gs=k_gs_now
        )
        
        # Measure progress
        min_now = _min_norm2(B)
        H_now = sum(entropy_row(B, i) for i in range(n)) / max(1, n)
        improved_this_loop = (min_now < current_min)
        
        # Flatness proxy: GS condition vs entropy
        m = StepMetrics(
            step=step_count,
            norm=float(min_now),
            grad_eff=float(current_min - min_now) if improved_this_loop else 0.0,
            geom_flat=1.0 if not improved_this_loop else 0.2,
            swaps=deep_count,
            extra={"H": H_now, "mode": mode.value}
        )
        gearbox.push(m)
        current_min = min_now
        
        # Break conditions
        if status == "corruption_detected":
            result.stop_reason = "corruption_trap"
            break
        
        # Entropy fuse
        max_h = max(math.log1p(_maxabs_row(B, i)) for i in range(n))
        critical_threshold = float(entropy_cap) + 6.0
        if max_h > critical_threshold:
            result.stop_reason = "entropy_fuse_tripped"
            break
            
        # If we completed LLL and didn't shift to micro, and not improved... maybe stop?
        if status == "completed" and mode == GearMode.DRILL and not improved_this_loop:
             if step_count > 1: # Give at least 2 chances
                 break

    min2 = _min_norm2(B)
    H2 = sum(entropy_row(B, i) for i in range(n)) / max(1, n)
    result.H_after = float(H2)
    result.min_norm2 = min2
    improved = (min2 > 0 and min_initial > 0 and min2 < min_initial)
    if not result.stop_reason:
        if not ledger.alive():
            result.stop_reason = "budget"
        else:
            result.stop_reason = "converged"

    # Score + best row
    norms = [norm2_exact(B[i]) for i in range(n)]
    best_idx = int(np.argmin(np.array(norms, dtype=np.int64)))
    result.min_norm2 = int(norms[best_idx])
    result.best_idx = best_idx
    result.J_score = objective_J(B)
    result.is_object = bool(is_object)
    result.deep_insert_count = int(deep_count)
    result.ua_spent = int(ledger.spent - ua_start)

    return B, U, result

# ============================================================
# K) PHASE A/B SCHEDULER (Floating Budget macro)
# ============================================================
def _dim_params(n: int) -> dict:
    if n <= 15:
        return {"attempts_A": 10, "K_select": 2, "block_B": 18}
    elif n <= 20:
        return {"attempts_A": 14, "K_select": 3, "block_B": 22}
    elif n <= 25:
        return {"attempts_A": 18, "K_select": 3, "block_B": 26}
    else:
        att = min(24, max(8, n))
        ks = min(5, max(2, n // 8))
        return {"attempts_A": att, "K_select": ks, "block_B": min(n, n + 2)}

def ua_engine_v2(basis: np.ndarray, **kwargs) -> Tuple[np.ndarray, Dict]:
    delta = float(kwargs.get("delta", 0.99))
    alpha_A = float(kwargs.get("alpha_A", 0.90))
    alpha_B = float(kwargs.get("alpha_B", 0.95))
    chaos_strength = int(kwargs.get("chaos_strength", 3))
    seed = kwargs.get("seed", None)

    n = basis.shape[0]
    rng = np.random.default_rng(seed)

    UA_total = int(kwargs.get("ua_budget", 100 * n * n))
    params = _dim_params(n)
    attempts_A = int(params["attempts_A"])
    K_select = int(params["K_select"])
    block_B = int(params["block_B"])

    UA_A = int(0.70 * UA_total)
    UA_B = int(UA_total - UA_A)
    UA_A_per = max(1, UA_A // max(1, attempts_A))
    UA_B_per = max(1, UA_B // max(1, K_select))

    k_gs_A = int(kwargs.get("k_gs_A", 30))
    k_gs_B = int(kwargs.get("k_gs_B", 15))

    # Entropy cap from initial basis (safe conversion)
    B0, _ = safe_int64_basis(basis)
    ecap = entropy_cap_compute(B0)

    # ---- PHASE A: Exploration ----
    phase_a_results: List[Tuple[Any, Any, UniverseResult]] = []
    aborted = 0
    reclaimed_ua = 0
    fallback_object_count = 0
    pool_extra = 0

    total_ledger = UALedger(budget=0)

    # Floating Budget trigger state
    H_hist: List[float] = []
    noimprove_entropic_streak = 0
    best_seen_min = None

    for a in range(attempts_A):
        budget_this = UA_A_per + pool_extra
        pool_extra = 0

        ledger_a = UALedger(budget=budget_this)

        B_a, U_a, res_a = run_universe(
            basis, ledger_a,
            delta=delta, alpha=alpha_A, block_size=10, k_gs=k_gs_A,
            chaos_strength=(chaos_strength if a > 0 else 0),
            entropy_cap=ecap, purge_tries=2,
            do_chaos=(a > 0), rng=rng,
        )
        phase_a_results.append((B_a, U_a, res_a))

        # Aggregate ledger
        total_ledger.mix += ledger_a.mix
        total_ledger.purge_try += ledger_a.purge_try
        total_ledger.purge_exec += ledger_a.purge_exec
        total_ledger.gs_full += ledger_a.gs_full
        total_ledger.lll_step += ledger_a.lll_step
        total_ledger.deep_search += ledger_a.deep_search

        # Abort reclaim
        if res_a.stop_reason in ["plateau_abort", "entropy_fuse_tripped", "corruption_trap"]:
            aborted += 1
            reclaimed = ledger_a.remaining
            reclaimed_ua += reclaimed
            pool_extra += reclaimed

        if res_a.is_object:
            fallback_object_count += 1

        # Floating Budget macro: 3 universes entropically worsening without min_norm2 improvement
        H_a = float(res_a.H_after)
        if best_seen_min is None:
            best_seen_min = res_a.min_norm2
        else:
            if res_a.min_norm2 < best_seen_min:
                best_seen_min = res_a.min_norm2
                noimprove_entropic_streak = 0
            else:
                medH = float(np.median(H_hist)) if H_hist else H_a
                if (H_a > medH) and (a > 0):
                    noimprove_entropic_streak += 1
                else:
                    noimprove_entropic_streak = 0

        if noimprove_entropic_streak >= 3:
            # temporary doubling via pool
            pool_extra += UA_A_per
            noimprove_entropic_streak = 0

        H_hist.append(H_a)

    # ---- SELECT TOP-K for Phase B ----
    scored = []
    for idx, (B_a, U_a, res_a) in enumerate(phase_a_results):
        H_a = sum(entropy_row(B_a, i) for i in range(n)) / max(1, n)
        scored.append((res_a.min_norm2, float(H_a), idx))
    scored.sort(key=lambda x: (x[0], x[1]))
    top_k_indices = [s[2] for s in scored[:K_select]]

    # ---- PHASE B: Exploitation ----
    best_B = None
    best_U = None
    best_norm2 = None
    best_J = float("inf")
    completed_B = 0

    for sel_idx in top_k_indices:
        B_sel, U_sel, res_sel = phase_a_results[sel_idx]
        ledger_b = UALedger(budget=UA_B_per)

        # Prepare cache
        if isinstance(B_sel, list):
            maxabs_b = [_maxabs_row(B_sel, i) for i in range(n)]
        else:
            maxabs_b = np.array([_maxabs_row(B_sel, i) for i in range(n)], dtype=np.int64)

        B_sel, U_sel, maxabs_b, is_obj_b, deep_b, status_b = deep_lll_v2(
            B_sel, U_sel, maxabs_b, ledger_b, bool(res_sel.is_object),
            delta=delta, alpha=alpha_B, block_size=block_B, k_gs=k_gs_B
        )

        # Aggregate
        total_ledger.gs_full += ledger_b.gs_full
        total_ledger.lll_step += ledger_b.lll_step
        total_ledger.deep_search += ledger_b.deep_search
        total_ledger.purge_try += ledger_b.purge_try
        total_ledger.purge_exec += ledger_b.purge_exec

        norms_b = [norm2_exact(B_sel[i]) for i in range(n)]
        idx_b = int(np.argmin(np.array(norms_b, dtype=np.int64)))
        ns_b = int(norms_b[idx_b])
        J_b = float(objective_J(B_sel))

        if best_B is None or J_b < best_J:
            best_B = B_sel
            best_U = U_sel
            best_norm2 = ns_b
            best_J = J_b

        if is_obj_b:
            fallback_object_count += 1
        completed_B += 1

    # ---- EXTRACTION ----
    norms_final = [norm2_exact(best_B[i]) for i in range(n)]
    final_idx = int(np.argmin(np.array(norms_final, dtype=np.int64)))
    coeffs_row = best_U[final_idx]

    out = np.zeros(n, dtype=np.int64)
    for i in range(n):
        out[i] = int(coeffs_row[i])

    # ---- LOG RECORD ----
    total_ledger.budget = UA_total
    log = {
        "n": n,
        "UA_total": UA_total,
        "UA_spent": total_ledger.spent,
        **total_ledger.snapshot(),
        "GS_full_count": total_ledger.gs_full,
        "purge_exec_count": total_ledger.purge_exec,
        "purge_try_count": total_ledger.purge_try,
        "deep_insert_exec_count": int(sum(r.deep_insert_count for _, _, r in phase_a_results)),
        "aborted_universes": int(aborted),
        "abort_reclaimed_UA": int(reclaimed_ua),
        "attempts_A": int(attempts_A),
        "completed_A": int(len(phase_a_results)),
        "K_select": int(K_select),
        "completed_B": int(completed_B),
        "fallback_object_universes": int(fallback_object_count),
        "BB_min_norm2": int(best_norm2 if best_norm2 is not None else 0),
        "kick_rate_A": float(np.mean([1.0 if r.kick_triggered else 0.0 for _, _, r in phase_a_results])) if phase_a_results else 0.0,
        "stop_reason": "budget",
    }
    return out, log

# ============================================================
# L) black_box_solver (warfare compatible)
# ============================================================
def black_box_solver(basis: np.ndarray, **kwargs: Any) -> np.ndarray:
    coeffs, _log = ua_engine_v2(basis, **kwargs)
    return coeffs

# ============================================================
# M) BENCH RUNNER (unchanged interface)
# ============================================================
def bench_runner():
    try:
        import importlib.util as _ilu
        import os
        _spec = _ilu.spec_from_file_location(
            "OPTIMA_CORE_SINGLEFILE",
            os.path.join(os.path.dirname(__file__), "OPTIMA_CORE_SINGLEFILE.py"),
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        lll_reduce = _mod.lll_reduce
    except Exception:
        lll_reduce = None

    dims = [15, 20, 25]
    seeds = list(range(1000, 1009))
    print("=" * 100)
    print("GAHENAX UA ENGINE V2 — BENCH RUNNER (PATCHED)")
    print("=" * 100)
    print(f"{'Dim':>4} {'Seed':>6} {'LLL norm':>12} {'UA norm':>12} "
          f"{'LLL ratio':>10} {'UA ratio':>10} {'Verdict':>8} {'UA_spent':>8} {'Kick%':>6} {'t(s)':>7}")
    print("-" * 100)
    from collections import defaultdict
    agg = defaultdict(lambda: {"lll": [], "ua": [], "times": [], "kicks": []})

    for dim in dims:
        for seed in seeds:
            print(f"Running Dim {dim} Seed {seed}...", end="\r")
            rng_ch = np.random.RandomState(seed)
            scales = np.array([1000 + 50 * i for i in range(dim)], dtype=np.int64)
            D = np.diag(scales)
            Umix = np.eye(dim, dtype=np.int64)
            for _ in range(8 * dim):
                ii = rng_ch.randint(0, dim)
                jj = rng_ch.randint(0, dim)
                if ii == jj:
                    continue
                kk = rng_ch.randint(-3, 4)
                if kk == 0:
                    continue
                Umix[ii] += kk * Umix[jj]
            basis = Umix @ D

            # GH
            log_det = float(np.sum(np.log(scales.astype(np.float64))))
            log_gh = 0.5 * (math.log(dim) - math.log(2 * math.pi * math.e)) + log_det / dim
            gh = math.exp(log_gh)

            # LLL baseline
            lll_norm = float("inf")
            if lll_reduce is not None:
                B_lll, U_lll, _, _ = lll_reduce(basis, delta=0.99)
                norms_lll = [float(np.linalg.norm(B_lll[i].astype(np.float64))) for i in range(dim)]
                lll_norm = min(norms_lll)

            # UA Engine V2 patched
            t0 = time.time()
            coeffs, log = ua_engine_v2(basis, delta=0.99, seed=seed)
            t1 = time.time()
            v = coeffs.astype(np.float64) @ basis.astype(np.float64)
            ua_norm = float(np.linalg.norm(v))

            lll_ratio = lll_norm / gh if gh > 0 else float("inf")
            ua_ratio = ua_norm / gh if gh > 0 else float("inf")

            if ua_norm < lll_norm - 1e-6:
                verdict = "WIN"
            elif abs(ua_norm - lll_norm) < 1e-6:
                verdict = "TIE"
            else:
                verdict = "LOSE"

            kickpct = 100.0 * float(log.get("kick_rate_A", 0.0))
            print(f"{dim:>4} {seed:>6} {lll_norm:>12.4f} {ua_norm:>12.4f} "
                  f"{lll_ratio:>10.4f} {ua_ratio:>10.4f} {verdict:>8} "
                  f"{log['UA_spent']:>8} {kickpct:>6.1f} {t1-t0:>7.2f}")

            agg[dim]["lll"].append(lll_ratio)
            agg[dim]["ua"].append(ua_ratio)
            agg[dim]["times"].append(t1 - t0)
            agg[dim]["kicks"].append(kickpct)

    print("=" * 100)
    print(f"{'Dim':>4} {'LLL mean':>11} {'UA mean':>11} {'UA best':>11} "
          f"{'Mean t':>8} {'Kick%':>7} {'Ties':>5} {'Wins':>5} {'Loses':>6}")
    print("-" * 100)
    for dim in dims:
        lll_r = agg[dim]["lll"]
        ua_r = agg[dim]["ua"]
        ts = agg[dim]["times"]
        kp = agg[dim]["kicks"]
        ties = sum(1 for l, u in zip(lll_r, ua_r) if abs(l - u) < 1e-6)
        wins = sum(1 for l, u in zip(lll_r, ua_r) if u < l - 1e-6)
        loses = len(lll_r) - ties - wins
        print(f"{dim:>4} {np.mean(lll_r):>11.4f} {np.mean(ua_r):>11.4f} "
              f"{min(ua_r):>11.4f} {np.mean(ts):>8.2f} {np.mean(kp):>7.1f} {ties:>5} {wins:>5} {loses:>6}")
    print("=" * 100)

if __name__ == "__main__":
    bench_runner()
