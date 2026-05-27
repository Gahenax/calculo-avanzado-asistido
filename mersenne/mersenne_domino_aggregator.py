#!/usr/bin/env python3
"""
MERSENNE DOMINO-WAVE AGGREGATOR
================================
Called after each block completes. Merges result into the master ledger,
checks gates, and logs cascade events.

Usage (called by Jules cascade hook):
    python scripts/mersenne_domino_aggregator.py --block <block_id>
"""

import json
import argparse
import hashlib
from pathlib import Path

LEDGER_DIR = Path("ledger_mersenne_domino")
RESULTS_DIR = Path("results/mersenne/domino_wave")

def load_result(block_id: int) -> dict:
    p = RESULTS_DIR / f"block_result_{block_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Block result not found: {p}")
    return json.loads(p.read_text())

def append_ledger(result: dict) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ledger = LEDGER_DIR / "master_ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")

def check_gates(result: dict) -> None:
    """Gate 2: escalate immediately if any prime found."""
    primes = result.get("primes_found", [])
    if primes:
        print(f"[GATE-2 TRIGGER] PRIME(S) FOUND: {primes}")
        print(f"  Block {result['block_id']} / Probe {result['probe']}")
        print(f"  Range: [{result['p_start']}, {result['p_end']}]")
        print(f"  ACTION: Escalate to FCD. Run independent verification.")
        # Write discovery alert
        alert = RESULTS_DIR / f"DISCOVERY_ALERT_block_{result['block_id']}.json"
        alert.write_text(json.dumps(result, indent=2))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--block", type=int, required=True)
    args = ap.parse_args()

    result = load_result(args.block)

    # Integrity check
    sha = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:16]
    print(f"[Block {args.block}] sha256_short={sha}  candidates={result.get('candidates_tested', '?')}")

    append_ledger(result)
    check_gates(result)
    print(f"[Block {args.block}] Aggregated OK.")

if __name__ == "__main__":
    main()
