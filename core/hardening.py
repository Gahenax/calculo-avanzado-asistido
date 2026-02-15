# -*- coding: utf-8 -*-
# hardening.py
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class HardeningConfig:
    eps_norm: float = 1e-12
    eps_dom: float = 1e-12
    eps_div: float = 1e-12

    fuse_window: int = 32
    tau_growth: float = 0.35          # median delta(log(norm)) above this => abort
    tau_cond_proxy: float = 1e10      # condition proxy above this => abort
    tau_sanitize_frac: float = 0.02   # clamp fraction above this => abort

    max_repeat_fail: int = 3
    toxic_cooldown: int = 200         # iterations to skip a toxic seed

    stagnation_window: int = 64       # optional: abort if no improvement
    stagnation_tol: float = 0.0       # improvement threshold (score must improve by > tol)


@dataclass
class UAStats:
    allocated: float
    spent: float = 0.0
    refund: float = 0.0


@dataclass
class SeedScore:
    fail_count: int = 0
    toxic_until_iter: int = 0
    last_fail_mode: str = ""


@dataclass
class FuseState:
    norm_log_hist: List[float] = field(default_factory=list)
    cond_proxy_hist: List[float] = field(default_factory=list)
    sanitize_frac_hist: List[float] = field(default_factory=list)
    score_hist: List[float] = field(default_factory=list)


def condition_proxy(A: np.ndarray, eps_norm: float) -> float:
    # Cheap proxy: Frobenius norm divided by min row norm.
    fro = float(np.linalg.norm(A, ord="fro"))
    row = np.linalg.norm(A, axis=1)
    mn = float(max(np.min(row), eps_norm))
    return fro / mn


def find_bad_rows(A: np.ndarray, eps_norm: float) -> List[int]:
    row = np.linalg.norm(A, axis=1)
    m = (~np.isfinite(row)) | (row < eps_norm)
    return np.where(m)[0].tolist()


def zero_isolation_reset(A: np.ndarray, idx: int, rng: np.random.Generator, eps_norm: float) -> np.ndarray:
    """
    Replace only row idx with a bounded random vector and light re-orthogonalization.
    Keeps universe alive without full restart.
    """
    n = A.shape[1]
    r = rng.standard_normal(n)

    others = np.delete(A, idx, axis=0)
    denom = np.sum(others * others, axis=1) + eps_norm
    proj = (others @ r) / denom
    r = r - (proj[:, None] * others).sum(axis=0)

    nr = float(max(np.linalg.norm(r), eps_norm))
    r = r / nr

    A2 = A.copy()
    A2[idx] = r
    return A2


def fuse_should_abort(fuse: FuseState, cfg: HardeningConfig) -> Tuple[bool, str]:
    w = cfg.fuse_window

    # 1) Growth fuse
    if len(fuse.norm_log_hist) >= w:
        hist = np.array(fuse.norm_log_hist[-w:], float)
        d = np.diff(hist)
        if float(np.median(d)) > cfg.tau_growth:
            return True, "entropy_growth"

    # 2) Condition fuse
    if len(fuse.cond_proxy_hist) >= w:
        if float(np.median(fuse.cond_proxy_hist[-w:])) > cfg.tau_cond_proxy:
            return True, "condition_collapse"

    # 3) Sanitization fuse
    if len(fuse.sanitize_frac_hist) >= w:
        if float(np.median(fuse.sanitize_frac_hist[-w:])) > cfg.tau_sanitize_frac:
            return True, "sanitize_overuse"

    return False, ""


def stagnation_should_abort(fuse: FuseState, cfg: HardeningConfig) -> Tuple[bool, str]:
    w = cfg.stagnation_window
    if w <= 1:
        return False, ""
    if len(fuse.score_hist) < w:
        return False, ""

    hist = np.array(fuse.score_hist[-w:], float)
    best_prev = float(np.min(hist[:-1]))
    now = float(hist[-1])
    # If no improvement beyond tol
    if now >= best_prev - cfg.stagnation_tol:
        return True, "stagnation"
    return False, ""


def ua_refund_on_abort(ua: UAStats) -> None:
    ua.refund += max(0.0, ua.allocated - ua.spent)


def seed_is_toxic(scores: Dict[int, SeedScore], seed: int, iter_i: int) -> bool:
    s = scores.get(seed)
    return (s is not None) and (iter_i < s.toxic_until_iter)


def mark_seed_fail(scores: Dict[int, SeedScore], seed: int, iter_i: int, cfg: HardeningConfig, mode: str) -> None:
    s = scores.setdefault(seed, SeedScore())
    s.fail_count += 1
    s.last_fail_mode = mode
    if s.fail_count >= cfg.max_repeat_fail:
        s.toxic_until_iter = iter_i + cfg.toxic_cooldown


def adaptive_retry_tweak(cfg: HardeningConfig, fail_mode: str) -> HardeningConfig:
    """
    Returns a modified config for retry attempts based on failure mode.
    Keep this conservative and monotonic.
    """
    c = HardeningConfig(**cfg.__dict__)
    if fail_mode == "entropy_growth":
        c.eps_norm *= 10.0
        c.tau_growth *= 0.9
    elif fail_mode == "condition_collapse":
        c.eps_norm *= 10.0
        c.tau_cond_proxy *= 0.9
    elif fail_mode == "sanitize_overuse":
        c.eps_dom *= 10.0
        c.tau_sanitize_frac *= 0.9
    elif fail_mode == "nonfinite":
        c.eps_norm *= 10.0
        c.eps_dom *= 10.0
        c.eps_div *= 10.0
    elif fail_mode == "stagnation":
        c.tau_growth *= 0.95
    return c
