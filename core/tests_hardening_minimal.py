# -*- coding: utf-8 -*-
# tests_hardening_minimal.py
from __future__ import annotations
import numpy as np
from hardening import HardeningConfig, FuseState, fuse_should_abort, find_bad_rows, zero_isolation_reset, UAStats, ua_refund_on_abort
from safe_math import SanityStats, sanitize_array

def test_zero_isolation():
    cfg = HardeningConfig()
    rng = np.random.default_rng(123)
    A = rng.standard_normal((8, 8))
    A[3] = 0.0
    bad = find_bad_rows(A, cfg.eps_norm)
    assert 3 in bad
    A2 = zero_isolation_reset(A, 3, rng, cfg.eps_norm)
    assert np.isfinite(A2).all()

def test_sanitize():
    stats = SanityStats()
    A = np.array([[np.nan, 1.0], [np.inf, -np.inf]])
    A2 = sanitize_array(A, stats)
    assert np.isfinite(A2).all()

if __name__ == "__main__":
    test_zero_isolation()
    test_sanitize()
    print("OK")
