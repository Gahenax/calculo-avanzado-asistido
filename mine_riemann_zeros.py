import sys
import json
import os
import time
from dataclasses import asdict
from typing import List, Dict, Any

# Add core to path to import utils
sys.path.append(os.path.join(os.getcwd(), "core"))

from riemann_pipeline_utils import (
    dedupe_candidates,
    tag_edges,
    classify_candidate,
    try_bracket_and_confirm,
)

# Import macro functionality
from RIEMANN_ZERO_FILTER_UA_MACRO import (
    tri_filter_scan, ScanConfig, UAConfig, PrecisionConfig, Thresholds, RiemannLedger, hardy_z
)

# Config
DEDUP_EPS = 0.075   # ~1.5*step si step=0.05
EDGE_STEPS = 2.0
BRENT_TOL = 1e-12
BRACKET_EXPAND_STEPS = 8
CHUNK_SIZE = 100.0
START_T = 14.0
END_T = 1014.0
RESULTS_FILE = "riemann_mining_results.jsonl"

def process_block(t1: float, t2: float, step: float = 0.05, budget: int = 200000):
    print(f"\n[ORCHESTRATOR] Processing block T=[{t1}, {t2}]...")
    
    # 1) Setup configs for the macro scan
    cfg_scan = ScanConfig(T0=t1, T1=t2, step=step)
    cfg_ua = UAConfig(budget_total=budget)
    cfg_prec = PrecisionConfig()
    thr = Thresholds()
    ledger = RiemannLedger(cfg_ua)

    # 2) Macro scan (returns list of Candidate objects)
    # Note: tri_filter_scan already performs some internal dedupe/tagging 
    # but we'll re-apply as requested for orchestrator-level control.
    candidates_obj = tri_filter_scan(cfg_scan, cfg_prec, thr, ledger)
    
    # Convert candidates to dicts
    candidates = []
    for c in candidates_obj:
        d = asdict(c)
        d["t_center"] = c.refined_T
        d["absZ"] = c.verified_s_full
        candidates.append(d)

    # 3) Edge tagging
    tag_edges(candidates, T1=t1, T2=t2, step=step, key_t="t_center", edge_steps=EDGE_STEPS)

    # 4) DEDUPE
    candidates_dedup = dedupe_candidates(candidates, key_t="t_center", eps=DEDUP_EPS, prefer="min_absZ")

    # 5) Confirmation and Classification
    results = []
    z_real_fn = lambda t: hardy_z(float(t), cfg_prec)

    for c in candidates_dedup:
        t0 = float(c.get("t_center"))
        out = dict(c)
        out["block_range"] = [t1, t2]
        
        # Confirmation determinista (bracketing + Brent)
        try:
            confirm = try_bracket_and_confirm(
                z_real=z_real_fn,
                t0=t0,
                step=step,
                expand_steps=BRACKET_EXPAND_STEPS,
                tol=BRENT_TOL,
            )
            out.update(confirm)
        except Exception as e:
            out.setdefault("status", "VALLEY_ONLY")
            out.setdefault("root_converged", False)
            out["confirm_error"] = str(e)

        # Clasificación dura
        out["status"] = classify_candidate(out)

        # Persistencia JSONL
        with open(RESULTS_FILE, "a") as f:
            f.write(json.dumps(out) + "\n")

        results.append(out)

    print(f"[ORCHESTRATOR] Found and verified {len(results)} candidates in block.")
    return results

def main():
    print("="*60)
    print("GAHENAX RIEMANN ZERO MINER - HARDENED ORCHESTRATOR")
    print("="*60)
    
    if os.path.exists(RESULTS_FILE):
        print(f"Clearing existing results at {RESULTS_FILE}...")
        os.remove(RESULTS_FILE)

    current_t = START_T
    while current_t < END_T:
        t_next = min(current_t + CHUNK_SIZE, END_T)
        process_block(current_t, t_next)
        current_t = t_next
        time.sleep(1)

    print("\ = 60")
    print(f"Mining complete. Results saved in {RESULTS_FILE}")
    print("="*60)

if __name__ == "__main__":
    main()
