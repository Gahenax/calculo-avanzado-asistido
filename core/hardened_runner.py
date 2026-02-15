import numpy as np
import sys
import os

# Ensure core is in path if run as script, but usually imported
sys.path.append(os.path.dirname(__file__))

from safe_math import SanityStats, sanitize_array
from hardening import (
    HardeningConfig, UAStats, FuseState,
    condition_proxy, find_bad_rows, zero_isolation_reset,
    fuse_should_abort, ua_refund_on_abort,
    seed_is_toxic, mark_seed_fail
)

def run_universe_hardened(seed: int, A_init: np.ndarray, step_fn, score_fn,
                         ua_budget: float, iter_max: int, cfg: HardeningConfig,
                         seed_scores: dict, global_iter0: int = 0):
    """
    Orchestrates a hardened universe execution using P over NP philosophy.
    Integrates SafeMath, ZeroIsolation, and EntropyFuses.
    """
    if seed_is_toxic(seed_scores, seed, global_iter0):
        return {"status": "SKIP_TOXIC", "seed": seed}

    rng = np.random.default_rng(seed)
    ua = UAStats(allocated=ua_budget)
    fuse = FuseState()
    sanity = SanityStats()
    A = A_init.copy()

    for t in range(iter_max):
        # 1) Sanitize (No NaN/Inf)
        A = sanitize_array(A, sanity)

        # 2) Zero Isolation (Recover from rank death/collapse)
        for idx in find_bad_rows(A, cfg.eps_norm):
            A = zero_isolation_reset(A, idx, rng, cfg.eps_norm)

        # 3) Update Telemetry
        fuse.cond_proxy_hist.append(condition_proxy(A, cfg.eps_norm))
        # Use Frobenius norm as a growth proxy
        f_norm = np.linalg.norm(A.astype(float), ord="fro")
        fuse.norm_log_hist.append(float(np.log(f_norm + cfg.eps_norm)))
        fuse.sanitize_frac_hist.append(float(sanity.clamp_log1p_frac))

        # 4) Action Step (P-governed move)
        # The step_fn should ideally use safe_math utilities internally
        A = step_fn(A, rng, cfg, sanity)

        # 5) UA Accounting
        ua.spent += 1.0
        if ua.spent >= ua.allocated:
            return {"status": "BUDGET_END", "seed": seed, "ua": ua, "sanity": sanity, "score": score_fn(A), "A": A}

        # 6) Thermal Fuse Check
        abort, mode = fuse_should_abort(fuse, cfg)
        if abort or (not np.isfinite(A.astype(float)).all()):
            fail = mode if abort else "nonfinite"
            ua_refund_on_abort(ua)
            mark_seed_fail(seed_scores, seed, global_iter0 + t, cfg)
            return {"status": "ABORT", "seed": seed, "fail_mode": fail, "ua": ua, "sanity": sanity}

    return {"status": "SURVIVE", "seed": seed, "ua": ua, "sanity": sanity, "score": score_fn(A), "A": A}
