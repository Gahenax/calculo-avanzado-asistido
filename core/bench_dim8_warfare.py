# -*- coding: utf-8 -*-
# bench_dim8_warfare.py
from __future__ import annotations

import json
import time
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np

# Path injection if root
sys.path.append(os.path.join(os.getcwd(), 'core'))

from governance_runtime import run_with_retries
from hardening import HardeningConfig


def example_step_fn(A: np.ndarray, rng: np.random.Generator, cfg: HardeningConfig, sanity) -> np.ndarray:
    noise = 0.01 * rng.standard_normal(A.shape)
    A2 = A + noise
    row_norms = np.linalg.norm(A2, axis=1, keepdims=True)
    row_norms = np.maximum(row_norms, cfg.eps_norm)
    A2 = A2 / row_norms
    return A2


def example_score_fn(A: np.ndarray) -> float:
    return float(np.linalg.norm(A, ord="fro"))


def run_benchmark(
    dims: List[int],
    seeds: List[int],
    ua_budget: float,
    iter_max: int,
    out_jsonl: str = "warfare_runs.jsonl",
) -> None:
    cfg = HardeningConfig()
    seed_scores: Dict[int, Any] = {}

    rows: List[Dict[str, Any]] = []
    t0 = time.time()

    for dim in dims:
        for seed in seeds:
            rng = np.random.default_rng(seed)
            A0 = rng.standard_normal((dim, dim)).astype(np.float64)

            ours = run_with_retries(
                seed=seed,
                A_init=A0,
                step_fn=example_step_fn,
                score_fn=example_score_fn,
                ua_budget=ua_budget,
                iter_max=iter_max,
                cfg=cfg,
                seed_scores=seed_scores,
                retries=2,
                global_iter0=0,
            )

            row = {
                "dim": dim,
                "seed": seed,
                "ours_status": ours.get("status"),
                "ours_fail_mode": ours.get("fail_mode", ""),
                "ours_score": ours.get("score", None),
                "ours_ua_spent": float(getattr(ours.get("ua"), "spent", ours.get("ua", {}).get("spent", 0.0)) if ours.get("ua") is not None else 0.0),
                "ours_ua_refund": float(getattr(ours.get("ua"), "refund", ours.get("ua", {}).get("refund", 0.0)) if ours.get("ua") is not None else 0.0),
                "ours_seconds": ours.get("seconds", None),
            }
            rows.append(row)

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dt = time.time() - t0

    # Summary
    succ = [r for r in rows if r["ours_status"] == "SURVIVE"]
    survival_rate = (len(succ) / max(1, len(rows)))

    print("Warfare summary")
    print(f"runs={len(rows)} dims={dims} ua_budget={ua_budget} iter_max={iter_max} wall_seconds={dt:.2f}")
    print(f"survival_rate={survival_rate:.4f}")

if __name__ == "__main__":
    dims = [8, 9, 10]
    seeds = list(range(0, 10))
    run_benchmark(dims=dims, seeds=seeds, ua_budget=200.0, iter_max=100)
