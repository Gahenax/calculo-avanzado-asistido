# -*- coding: utf-8 -*-
# governance_runtime.py
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import numpy as np

from safe_math import SanityStats, sanitize_array
from hardening import (
    HardeningConfig, UAStats, FuseState,
    condition_proxy, find_bad_rows, zero_isolation_reset,
    fuse_should_abort, stagnation_should_abort,
    ua_refund_on_abort, seed_is_toxic, mark_seed_fail,
    adaptive_retry_tweak
)

StepFn = Callable[[np.ndarray, np.random.Generator, HardeningConfig, SanityStats], np.ndarray]
ScoreFn = Callable[[np.ndarray], float]


def run_universe_hardened(
    seed: int,
    A_init: np.ndarray,
    step_fn: StepFn,
    score_fn: ScoreFn,
    ua_budget: float,
    iter_max: int,
    cfg: HardeningConfig,
    seed_scores: Dict[int, Any],
    global_iter0: int = 0,
) -> Dict[str, Any]:
    """
    Executes a single universe with:
    - SafeMath sanitation
    - Zero Isolation
    - Entropy fuse + optional stagnation fuse
    - UA accounting + refund
    """
    if seed_is_toxic(seed_scores, seed, global_iter0):
        return {"status": "SKIP_TOXIC", "seed": seed}

    rng = np.random.default_rng(seed)
    ua = UAStats(allocated=ua_budget)
    fuse = FuseState()
    sanity = SanityStats()
    A = A_init.copy()
    initial_score = float(score_fn(A))
    resets = 0

    t0 = time.time()

    for t in range(iter_max):
        # 1) Sanitize
        A = sanitize_array(A, sanity)

        # 2) Zero Isolation
        bad_rows = find_bad_rows(A, cfg.eps_norm)
        if bad_rows:
            resets += len(bad_rows)
            for idx in bad_rows:
                A = zero_isolation_reset(A, idx, rng, cfg.eps_norm)

        # 3) Track fuse metrics (pre-step)
        fuse.cond_proxy_hist.append(condition_proxy(A, cfg.eps_norm))
        fuse.norm_log_hist.append(float(np.log(np.linalg.norm(A, ord="fro") + cfg.eps_norm)))
        fuse.sanitize_frac_hist.append(float(sanity.clamp_log1p_frac))

        # 4) Step
        A = step_fn(A, rng, cfg, sanity)

        ua.spent += 1.0
        if ua.spent >= ua.allocated:
            dt = time.time() - t0
            return {
                "status": "BUDGET_END", "seed": seed, "ua": ua, "sanity": sanity, 
                "seconds": dt, "resets": resets, "initial_score": initial_score, "final_score": sc
            }

        # 5) Score and stagnation tracking (optional but useful)
        sc = float(score_fn(A))
        fuse.score_hist.append(sc)

        # 6) Hard invariants
        if not np.isfinite(A).all():
            ua_refund_on_abort(ua)
            mark_seed_fail(seed_scores, seed, global_iter0 + t, cfg, "nonfinite")
            dt = time.time() - t0
            return {
                "status": "ABORT", "seed": seed, "fail_mode": "nonfinite", "ua": ua, "sanity": sanity, 
                "seconds": dt, "resets": resets, "initial_score": initial_score, "final_score": sc
            }

        # 7) Fuse checks
        abort, mode = fuse_should_abort(fuse, cfg)
        if abort:
            ua_refund_on_abort(ua)
            mark_seed_fail(seed_scores, seed, global_iter0 + t, cfg, mode)
            dt = time.time() - t0
            return {
                "status": "ABORT", "seed": seed, "fail_mode": mode, "ua": ua, "sanity": sanity, 
                "seconds": dt, "resets": resets, "initial_score": initial_score, "final_score": sc
            }

        abort2, mode2 = stagnation_should_abort(fuse, cfg)
        if abort2:
            ua_refund_on_abort(ua)
            mark_seed_fail(seed_scores, seed, global_iter0 + t, cfg, mode2)
            dt = time.time() - t0
            return {
                "status": "ABORT", "seed": seed, "fail_mode": mode2, "ua": ua, "sanity": sanity, 
                "seconds": dt, "resets": resets, "initial_score": initial_score, "final_score": sc
            }

    dt = time.time() - t0
    sc_final = float(score_fn(A))
    return {
        "status": "SURVIVE", "seed": seed, "ua": ua, "sanity": sanity, "seconds": dt, 
        "initial_score": initial_score, "final_score": sc_final, "resets": resets, "A": A
    }


def run_with_retries(
    seed: int,
    A_init: np.ndarray,
    step_fn: StepFn,
    score_fn: ScoreFn,
    ua_budget: float,
    iter_max: int,
    cfg: HardeningConfig,
    seed_scores: Dict[int, Any],
    retries: int = 2,
    global_iter0: int = 0,
) -> Dict[str, Any]:
    """
    Retry policy: if ABORT, tweak cfg based on fail_mode and retry with a derived seed.
    """
    out = run_universe_hardened(seed, A_init, step_fn, score_fn, ua_budget, iter_max, cfg, seed_scores, global_iter0)
    if out.get("status") != "ABORT":
        return out

    base_mode = str(out.get("fail_mode", "unknown"))
    cfg2 = adaptive_retry_tweak(cfg, base_mode)

    for k in range(retries):
        # Derived seed to avoid repeating identical chaos
        seed_k = (seed ^ (0x9E3779B97F4A7C15 & 0xFFFFFFFF)) + (k + 1) * 1337
        out_k = run_universe_hardened(seed_k, A_init, step_fn, score_fn, ua_budget, iter_max, cfg2, seed_scores, global_iter0)
        if out_k.get("status") != "ABORT":
            out_k["retry_from_seed"] = seed
            out_k["retry_fail_mode"] = base_mode
            return out_k

        cfg2 = adaptive_retry_tweak(cfg2, str(out_k.get("fail_mode", "unknown")))

    return out
