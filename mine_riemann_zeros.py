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
    bracketing_scan, ScanConfig, UAConfig, PrecisionConfig, Thresholds, RiemannLedger, hardy_z
)
from riemann_pipeline_utils import n_riemann_von_mangoldt

# Config
DEFAULT_ALPHA = 0.25
CHUNK_SIZE = 100.0
START_T = 14.0
END_T = 1014.0
RESULTS_FILE = "riemann_mining_results.jsonl"
DEFICIT_THRESHOLD = 2  # Trigger correction if > 2 zeros missed per block

def process_block(t1: float, t2: float, alpha: float = 0.25, budget: int = 500000):
    print(f"\n[ORCHESTRATOR] Processing block T=[{t1:.1f}, {t2:.1f}] with alpha={alpha:.3f}...")
    
    # 1) Setup configs
    cfg_scan = ScanConfig(T0=t1, T1=t2, step=alpha) # We use step field for alpha
    cfg_ua = UAConfig(budget_total=budget)
    cfg_prec = PrecisionConfig()
    ledger = RiemannLedger(cfg_ua)

    # 2) Industrial Bracketing Scan
    candidates_obj = bracketing_scan(cfg_scan, cfg_prec, ledger, alpha=alpha)
    
    # 3) Convert to dicts and tag
    results = [asdict(c) for c in candidates_obj]
    for r in results:
        r["block_range"] = [t1, t2]
        r["status"] = classify_candidate(r)
        # Persistence
        with open(RESULTS_FILE, "a") as f:
            f.write(json.dumps(r) + "\n")

    # 4) AUDIT
    expected = int(round(n_riemann_von_mangoldt(t2) - n_riemann_von_mangoldt(t1)))
    observed = len(results)
    deficit = expected - observed
    
    print(f"[ORCHESTRATOR] Block Stats: Expected={expected}, Observed={observed}, Deficit={deficit}")
    return observed, expected, deficit

def main():
    print("="*60)
    print("GAHENAX RIEMANN ZERO MINER - INDUSTRIAL v2.0")
    print("Sign-Change Detection + Audit-by-Count active")
    print("="*60)
    
    if os.path.exists(RESULTS_FILE):
        print(f"Clearing existing results at {RESULTS_FILE}...")
        os.remove(RESULTS_FILE)

    current_t = START_T
    alpha = DEFAULT_ALPHA
    total_found = 0
    total_expected = 0

    while current_t < END_T:
        t_next = min(current_t + CHUNK_SIZE, END_T)
        
        found, expected, deficit = process_block(current_t, t_next, alpha=alpha)
        
        total_found += found
        total_expected += expected
        
        # SELF-CORRECTION LOGIC
        if deficit > DEFICIT_THRESHOLD:
            print(f"[CORRECTION] Deficit {deficit} > {DEFICIT_THRESHOLD}. Tightening alpha for next block.")
            alpha = max(0.05, alpha * 0.7) # Reduce step size
        elif deficit <= 0 and alpha < DEFAULT_ALPHA:
            print(f"[CORRECTION] Zero deficit. Slightly relaxing alpha.")
            alpha = min(DEFAULT_ALPHA, alpha * 1.1)

        current_t = t_next
        time.sleep(0.5)

    print("\n" + "="*60)
    print(f"INDUSTRIAL MINING COMPLETE.")
    print(f"Total Expected (N(T)): {total_expected}")
    print(f"Total Found: {total_found}")
    print(f"Yield: {(total_found/total_expected)*100:.1f}%")
    print(f"Results saved in {RESULTS_FILE}")
    print("="*60)

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
