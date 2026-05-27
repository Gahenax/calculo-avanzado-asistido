#!/usr/bin/env python3
"""
MERSENNE TRAMPOLINE AGGREGATOR
================================
Called after each probe completes.
Handles anchors, gaps, and frontier blocks.
"""
import json
import argparse
import hashlib
import sys
from pathlib import Path

OUT   = Path("results/mersenne/trampoline")
LED   = Path("ledger_mersenne_trampoline")
CALIB = OUT / "ghost_calibration.json"

def load_calib():
    if CALIB.exists():
        return json.loads(CALIB.read_text())
    return {"z_scores": [], "threshold": 2.0, "n_anchors": 0}

def save_calib(c):
    OUT.mkdir(parents=True, exist_ok=True)
    CALIB.write_text(json.dumps(c, indent=2))

def append_ledger(result):
    LED.mkdir(parents=True, exist_ok=True)
    with (LED / "master.jsonl").open("a") as f:
        f.write(json.dumps(result) + "\n")

def process_anchor(result):
    """Gate 0: anchor must confirm PRIME."""
    p = result["p"]
    ll = result.get("ll_result")
    if ll != "PRIME":
        print(f"[GATE-0 FAIL] Anchor M_{p}: expected PRIME, got {ll}")
        print("  !! HALTING — LL implementation error. Abort all probes.")
        sys.exit(1)
    z = result.get("ghost_z", 0.0)
    c = load_calib()
    c["z_scores"].append({"p": p, "z": z})
    c['n_anchors'] += 1
    if c['n_anchors'] >= 5:
        zs = [x["z"] for x in c["z_scores"]]
        import statistics
        mu    = statistics.mean(zs)
        sigma = statistics.stdev(zs) if len(zs) > 1 else 1.0
        new_thresh = max(1.5, mu - 1.5 * sigma)
        c['threshold'] = round(new_thresh, 4)
        print(f"  [Ghost calibration] New threshold = {c['threshold']:.4f}"
              f"  (mean_z={mu:.3f}, sigma={sigma:.3f})")
    save_calib(c)
    print(f"  [Anchor M_{p}] OK. z={z:.3f}  calibration_n={c['n_anchors']}")

def process_gap(result):
    """Gate 1: if any prime found, escalate."""
    primes = result.get("primes_found", [])
    if primes:
        print(f"[GATE-1 DISCOVERY] Gap probe found PRIMES: {primes}")
        (OUT / f"DISCOVERY_GAP_{result['p_lo']}_{result['p_hi']}.json").write_text(
            json.dumps(result, indent=2))
    else:
        print(f"  [Gap {result['p_lo']}-{result['p_hi']}] Empty as expected.")

def process_frontier(result):
    """Gate 2: prime in frontier = new Mersenne candidate."""
    primes = result.get("primes_found", [])
    if primes:
        print(f"[GATE-2 CRITICAL] Frontier prime(s): {primes}")
        print(f"  Submit to GIMPS. Run independent re-verification.")
        (OUT / f"DISCOVERY_FRONTIER_{result['probe_id']}.json").write_text(
            json.dumps(result, indent=2))
    else:
        print(f"  [Frontier {result.get('probe_id')}] No primes. Candidates={result.get('candidates_tested','?')}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe_type", required=True, choices=["ANCHOR","GAP","FRONTIER"])
    ap.add_argument("--result_file", required=True)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    result = json.loads(Path(args.result_file).read_text())
    append_ledger(result)

    if args.probe_type == "ANCHOR":
        process_anchor(result)
    elif args.probe_type == "GAP":
        process_gap(result)
    elif args.probe_type == "FRONTIER":
        process_frontier(result)

if __name__ == "__main__":
    main()
