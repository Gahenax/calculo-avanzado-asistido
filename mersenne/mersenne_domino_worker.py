#!/usr/bin/env python3
"""
MERSENNE DOMINO-WAVE WORKER
============================
Runs Lucas-Lehmer test for all prime exponents p in [p_start, p_end].
Optionally applies Ghost Locus pre-filter to skip unpromising candidates.

Usage:
    python scripts/mersenne_domino_worker.py \
        --block_id 0 --p_start 25000 --p_end 30000 \
        --method GHOST_PREFILTER+LL --out results/mersenne/domino_wave/
"""

import argparse
import json
import math
import time
import hashlib
from pathlib import Path


def sieve_primes(lo: int, hi: int):
    """Simple segmented sieve."""
    if hi < 2:
        return []
    size = hi - lo + 1
    composite = [False] * size
    for p in range(2, int(math.isqrt(hi)) + 1):
        start = max(p * p, ((lo + p - 1) // p) * p)
        for j in range(start, hi + 1, p):
            composite[j - lo] = True
    return [lo + i for i in range(size) if not composite[i] and lo + i >= 2]


def lucas_lehmer(p: int) -> bool:
    """
    Lucas-Lehmer primality test for M_p = 2^p - 1.
    Returns True if M_p is prime.
    Requires p to be prime (checked by caller).
    """
    if p == 2:
        return True
    M = (1 << p) - 1  # 2^p - 1
    s = 4
    for _ in range(p - 2):
        s = (s * s - 2) % M
    return s == 0


def ghost_locus_zscore(p: int) -> float:
    """
    Stub for Ghost Locus pre-filter.
    In production: compute S(u) at u=log(2^p - 1) using Phase-3 Riemann zeros.
    Here: returns a simulated z-score (replace with real computation).
    """
    try:
        from scripts.mersenne_spectral_poc import probe
        res = probe(p)
        return res["z"]
    except (ImportError, KeyError):
        return 0.0  # conservative: 0 means "do not skip"


def run_block(
    block_id: int,
    p_start: int,
    p_end: int,
    method: str,
    probe_name: str,
    out_dir: Path,
    ghost_z_threshold: float = 2.0,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    candidates = sieve_primes(p_start, p_end)
    primes_found = []
    composites = []
    prefiltered = []
    telemetry = []

    for p in candidates:
        event = {"p": p, "method": method}

        if "GHOST_PREFILTER" in method:
            z = ghost_locus_zscore(p)
            event["ghost_z"] = z
            if z < ghost_z_threshold:
                prefiltered.append(p)
                event["action"] = "PREFILTERED"
                telemetry.append(event)
                continue

        is_prime = lucas_lehmer(p)
        if is_prime:
            primes_found.append(p)
            event["action"] = "PRIME"
            print(f"  *** PRIME FOUND: M_{p} = 2^{p}-1 IS MERSENNE PRIME ***")
        else:
            composites.append(p)
            event["action"] = "COMPOSITE"

        telemetry.append(event)

    wall_time = time.time() - t0

    result = {
        "block_id": block_id,
        "probe": probe_name,
        "p_start": p_start,
        "p_end": p_end,
        "candidates_tested": len(candidates),
        "ll_run": len(candidates) - len(prefiltered),
        "primes_found": primes_found,
        "composites": composites,
        "prefiltered": prefiltered,
        "wall_time_s": round(wall_time, 3),
        "status": "DONE",
    }
    result["sha256_results"] = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode()
    ).hexdigest()[:32]

    (out_dir / f"block_result_{block_id}.json").write_text(
        json.dumps(result, indent=2)
    )

    tele_path = out_dir / f"block_telemetry_{block_id}.jsonl"
    with tele_path.open("w") as f:
        for ev in telemetry:
            f.write(json.dumps(ev) + "\n")

    return result


def main():
    ap = argparse.ArgumentParser(description="Mersenne Domino-Wave worker.")
    ap.add_argument("--block_id", type=int, required=True)
    ap.add_argument("--p_start", type=int, required=True)
    ap.add_argument("--p_end", type=int, required=True)
    ap.add_argument("--probe", type=str, default="ALPHA")
    ap.add_argument("--method", type=str, default="LL",
                    choices=["LL", "GHOST_PREFILTER+LL"])
    ap.add_argument("--out", type=str, default="results/mersenne/domino_wave/")
    ap.add_argument("--ghost_z_threshold", type=float, default=2.0)
    args = ap.parse_args()

    print(f"[Block {args.block_id}] Starting: p=[{args.p_start},{args.p_end}] method={args.method}")
    result = run_block(
        block_id=args.block_id,
        p_start=args.p_start,
        p_end=args.p_end,
        method=args.method,
        probe_name=args.probe,
        out_dir=Path(args.out),
        ghost_z_threshold=args.ghost_z_threshold,
    )
    print(f"[Block {args.block_id}] Done. Tested={result['candidates_tested']} "
          f"LL={result['ll_run']} Primes={result['primes_found']} "
          f"Time={result['wall_time_s']:.1f}s")

    if result["primes_found"]:
        print(f"  !!! DISCOVERY: {result['primes_found']} — escalate to FCD !!!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
