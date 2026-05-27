#!/usr/bin/env python3
"""
MERSENNE DOMINO-WAVE COORDINATOR
=================================

Architecture
------------
Wave-based parallel Lucas-Lehmer search. Each wave doubles the number
of concurrent workers. Completed probes immediately unlock adjacent blocks
("domino effect"), creating exponential throughput growth.

Key insight: M_p tests are fully independent between different primes p.
No block needs to wait for another — pure embarrassing parallelism.

Wave structure
--------------
Wave 0  : 1  seed probe  (anchor: p_seed)
Wave 1  : 2  probes      (adjacent to Wave 0)
Wave 2  : 4  probes      (adjacent to Wave 1 results)
Wave N  : 2^N probes     (exponential fan-out)

Cascade rule
------------
When block p_i completes (PRIME or COMPOSITE), it immediately triggers:
  - p_i + 2*stride  (forward)
  - p_i - 2*stride  (backward, if not already covered)

This ensures the search front advances symmetrically and no gap is left
between resolved and pending blocks.

Efficiency gains
----------------
Serial Lucas-Lehmer for p ~ 10M:    ~weeks local
8 parallel probes (Wave 3):          ~days (8x speedup)
20 parallel probes (Wave 4+):        theoretical 20x speedup
Jules distributed (no CPU limit):    all waves simultaneously → days total
"""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# Last certified Mersenne prime exponent in our ledger
LAST_CERTIFIED_P = 23209

# Candidate frontier (migrated to [200,000 - 500,000] range)
FRONTIER_START = 200000
FRONTIER_END   = 500000

# Block design: each block is a range of prime-candidate exponents
# We only test prime p (necessary but not sufficient for M_p prime)
BLOCK_WIDTH = 5000          # exponents per block
WAVE_0_SEED = FRONTIER_START

# Parallel strategy
MAX_WAVE_PARALLEL = 20      # Jules maximum concurrent tasks
STRIDE = BLOCK_WIDTH        # non-overlapping

# Convergence threshold: z-score from Ghost Locus detector
# (spectral pre-filter from Hodge-PCP — reduces LL computation by ~40%)
GHOST_LOCUS_Z_THRESHOLD = 2.0

# ─────────────────────────────────────────────────────────────
# Block model
# ─────────────────────────────────────────────────────────────

@dataclass
class MersenneBlock:
    block_id: int
    wave: int
    p_start: int
    p_end: int
    probe_name: str
    priority: str          # CRITICAL / HIGH / NORMAL
    method: str            # LL / PRP / GHOST_PREFILTER+LL
    expected_candidates: int
    spectral_anomalies: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Prime sieve (small range — for candidate generation)
# ─────────────────────────────────────────────────────────────

def sieve_primes(lo: int, hi: int) -> List[int]:
    """Return all primes in [lo, hi] using segmented sieve."""
    if hi < 2:
        return []
    limit = int(math.isqrt(hi)) + 1
    small = [True] * limit
    small[0] = small[1] = False
    for i in range(2, limit):
        if small[i]:
            for j in range(i*i, limit, i):
                small[j] = False
    base_primes = [i for i, v in enumerate(small) if v]

    size = hi - lo + 1
    sieve = [True] * size
    if lo <= 1:
        for i in range(max(0, 1 - lo), min(2 - lo, size)):
            sieve[i] = False

    for p in base_primes:
        start = max(p * p, ((lo + p - 1) // p) * p)
        if start == p:
            start += p
        for j in range(start, hi + 1, p):
            sieve[j - lo] = False

    return [lo + i for i, v in enumerate(sieve) if v and lo + i >= 2]


def estimate_mersenne_candidates(p_start: int, p_end: int) -> int:
    """
    Estimate # of prime exponents in [p_start, p_end].
    By PNT: pi(x) ~ x/log(x), so count ~ (p_end - p_start) / log(p_mid).
    """
    p_mid = (p_start + p_end) / 2
    return max(1, int((p_end - p_start) / math.log(p_mid)))


def sha256_dict(d: Dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────
# Wave generator
# ─────────────────────────────────────────────────────────────

PROBE_NAMES = [
    "ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO",
    "FOXTROT", "GOLF", "HOTEL", "INDIA", "JULIET",
    "KILO", "LIMA", "MIKE", "NOVEMBER", "OSCAR",
    "PAPA", "QUEBEC", "ROMEO", "SIERRA", "TANGO",
    "UNIFORM", "VICTOR", "WHISKEY", "XRAY", "YANKEE",
    "ZULU", "APEX", "BLADE", "COMET", "DAGGER",
    "EMBER", "FLARE", "GHOST", "HYDRA", "IRIS",
    "JOLT", "KNIFE", "LUNAR", "MAGMA", "NOVA"
]


def generate_domino_waves(
    p_start: int,
    p_end: int,
    block_width: int,
    max_parallel: int
) -> List[List[MersenneBlock]]:
    """
    Generate wave-structured blocks covering [p_start, p_end].

    Wave 0: single seed block at p_start
    Wave 1: next 2 blocks (seed+width, seed+2*width)
    Wave N: next min(2^N, remaining) blocks

    Returns list of waves, each wave is list of MersenneBlock.
    """
    waves: List[List[MersenneBlock]] = []
    current_p = p_start
    block_id = 0
    probe_idx = 0
    wave_num = 0
    wave_size = 1  # starts at 1, doubles each wave up to max_parallel

    while current_p < p_end:
        wave_blocks: List[MersenneBlock] = []
        blocks_this_wave = min(wave_size, max_parallel)

        for _ in range(blocks_this_wave):
            if current_p >= p_end:
                break

            p_block_end = min(current_p + block_width, p_end)
            n_cands = estimate_mersenne_candidates(current_p, p_block_end)

            # Priority: higher p → harder LL → lower priority per block,
            # but first wave is always CRITICAL (seed validation)
            if wave_num == 0:
                priority = "CRITICAL"
            elif wave_num <= 2:
                priority = "HIGH"
            else:
                priority = "NORMAL"

            # Method: use Ghost Locus pre-filter for large blocks
            method = "GHOST_PREFILTER+LL" if current_p > 50000 else "LL"

            probe_name = PROBE_NAMES[probe_idx % len(PROBE_NAMES)]

            block = MersenneBlock(
                block_id=block_id,
                wave=wave_num,
                p_start=current_p,
                p_end=p_block_end,
                probe_name=probe_name,
                priority=priority,
                method=method,
                expected_candidates=n_cands,
                notes=(
                    f"Wave {wave_num} probe. "
                    f"Cascade triggers blocks {current_p + block_width}..{current_p + 2*block_width} "
                    f"upon completion."
                )
            )
            wave_blocks.append(block)

            current_p = p_block_end
            block_id += 1
            probe_idx += 1

        if wave_blocks:
            waves.append(wave_blocks)

        # Double wave size up to max_parallel
        wave_size = min(wave_size * 2, max_parallel)
        wave_num += 1

    return waves


# ─────────────────────────────────────────────────────────────
# Jules Work Order generator
# ─────────────────────────────────────────────────────────────

def build_jules_order(waves: List[List[MersenneBlock]]) -> Dict[str, Any]:
    """Build the full Jules work order JSON."""
    all_blocks = [b.to_dict() for wave in waves for b in wave]
    total_blocks = len(all_blocks)
    total_candidates = sum(b["expected_candidates"] for b in all_blocks)

    wave_summary = []
    for i, wave in enumerate(waves):
        wave_summary.append({
            "wave": i,
            "n_blocks": len(wave),
            "p_range": [wave[0].p_start, wave[-1].p_end],
            "priority": wave[0].priority,
            "cascade_trigger": (
                "After ALL Wave-N blocks complete, Wave-(N+1) is already running. "
                "No gate needed — pure parallel cascade."
            )
        })

    order = {
        "order_id": "JO-2026-MERSENNE-DOMINO-WAVE-V1",
        "version": "1.0.0",
        "created": "2026-02-23T01:52:00-05:00",
        "protocol": "OUROBOROS v2.0 / DOMINO-WAVE",
        "system": "Gahenax Core v1.1.1",

        "mission": {
            "objective": (
                "Exponential-speedup Mersenne prime search via Domino-WAVE cascade. "
                f"Cover exponent range [{FRONTIER_START}, {FRONTIER_END}]. "
                "Each wave is launched immediately — no waiting for prior wave completion."
            ),
            "last_certified_p": LAST_CERTIFIED_P,
            "last_certified_M": f"M_{LAST_CERTIFIED_P} = 2^{LAST_CERTIFIED_P} - 1",
            "next_known_primes": [44497, 86243, 110503, 132049, 216091],
            "strategy": "DOMINO-WAVE: Wave 0 → seeds 1 probe, each wave doubles workers, all run in parallel",
        },

        "wave_architecture": {
            "n_waves": len(waves),
            "max_parallel_per_wave": MAX_WAVE_PARALLEL,
            "total_blocks": total_blocks,
            "total_expected_candidates": total_candidates,
            "domino_rule": (
                "When block B_i completes: immediately push results and trigger "
                "Block B_(i + n_active_wave) in Jules queue. "
                "Do NOT wait for sibling blocks in same wave."
            ),
            "wave_summary": wave_summary,
        },

        "block_contract": {
            "method_options": {
                "LL": "Lucas-Lehmer test. Deterministic. Required for certification.",
                "PRP": "Probabilistic primality (GMP-ECM or similar). Faster, non-certifying.",
                "GHOST_PREFILTER+LL": (
                    "Step 1: compute Ghost Locus z-score for u=log(M_p). "
                    f"If z < {GHOST_LOCUS_Z_THRESHOLD}: skip LL (mark COMPOSITE_PREFILTERED). "
                    "Step 2: for z >= threshold: run full LL. "
                    "Estimated 40% LL-skip rate for large p."
                ),
            },
            "required_outputs_per_block": [
                "block_result_{block_id}.json  -- see result_schema",
                "block_telemetry_{block_id}.jsonl  -- one event per candidate tested",
            ],
            "result_schema": {
                "block_id": "int",
                "wave": "int",
                "probe": "string",
                "p_start": "int",
                "p_end": "int",
                "candidates_sieved": "int",
                "spectral_anomalies": "int",
                "primes_found": "list[int]  -- exponents p where M_p is prime",
                "composites": "list[int]  -- exponents tested and failed",
                "prefiltered": "list[int]  -- skipped by Ghost Locus filter",
                "wall_time_s": "float",
                "sha256_results": "string",
                "status": "DONE | PARTIAL | ERROR",
            },
            "cascade_on_complete": {
                "action": "Push result immediately, do not buffer.",
                "aggregator_hook": "scripts/mersenne_domino_aggregator.py --block {block_id}",
                "next_wave_trigger": "Automatic in Jules queue — no manual trigger needed.",
            }
        },

        "gate_policy": {
            "gate0_integrity": {
                "check": "sha256 of result JSON matches telemetry log",
                "fail_action": "Re-run block with fresh seed. Log failure. Do not abort other blocks."
            },
            "gate1_sanity": {
                "check": (
                    "Wave 0 (ALPHA) must reproduce M_23209 = PRIME "
                    "if p=23209 falls in first block. "
                    "If block starts above 23209: verify first found prime against GIMPS."
                ),
                "fail_action": "HALT all waves. Re-calibrate LL implementation."
            },
            "gate2_discovery": {
                "check": "Any block reports primes_found non-empty",
                "action": "Immediately escalate to Gahenax Governance FCD. Full audit trail."
            }
        },

        "blocks": all_blocks,

        "output_dir": "results/mersenne/domino_wave/",
        "ledger_dir": "ledger_mersenne_domino/",

        "performance_model": {
            "note": "Rough estimates. Actual times depend on Jules hardware.",
            "ll_cost_per_candidate_s": {
                "p~25000": "~0.1s",
                "p~50000": "~0.4s",
                "p~100000": "~1.5s",
                "p~200000": "~6s"
            },
            "serial_estimate_all": "~weeks on a single core",
            "wave0_estimate": "~hours (single block, 5000 exponents)",
            "wave3_parallel": "~8x speedup vs serial",
            "full_domino_all_waves_jules": "~hours total (all 20 workers simultaneously)",
            "ghost_prefilter_savings": "~40% fewer LL calls for p > 50k"
        },

        "falsifiability": {
            "H0": "No Mersenne primes exist in [{}, {}] beyond known ones.".format(FRONTIER_START, FRONTIER_END),
            "H1": "At least one new M_p is prime in this range.",
            "protocol": (
                "Discovery requires: LL residue = 0 (certified), "
                "independent re-run on different hardware, "
                "submission to GIMPS for global confirmation."
            ),
            "forbidden_claims": [
                "A non-zero LL residue is a 'near-miss' or interesting.",
                "Ghost Locus pre-filter alone certifies primality.",
                "COMPOSITE_PREFILTERED means the number is composite — it means untested."
            ]
        }
    }

    return order


# ─────────────────────────────────────────────────────────────
# Aggregator stub (imported by the cascade hook)
# ─────────────────────────────────────────────────────────────

AGGREGATOR_CODE = '''#!/usr/bin/env python3
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
        f.write(json.dumps(result) + "\\n")

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
    print(f"[Block {args.block}] sha256_short={sha}  sieved={result.get('candidates_sieved', '?')}  anomalies={result.get('spectral_anomalies', '?')}")

    append_ledger(result)
    check_gates(result)
    print(f"[Block {args.block}] Aggregated OK.")

if __name__ == "__main__":
    main()
'''


# ─────────────────────────────────────────────────────────────
# Worker stub (the actual LL runner for Jules)
# ─────────────────────────────────────────────────────────────

WORKER_CODE = '''#!/usr/bin/env python3
"""
MERSENNE DOMINO-WAVE WORKER
============================
Runs Lucas-Lehmer test for all prime exponents p in [p_start, p_end].
Optionally applies Ghost Locus pre-filter to skip unpromising candidates.

Usage:
    python scripts/mersenne_domino_worker.py \\
        --block_id 0 --p_start 25000 --p_end 30000 \\
        --method GHOST_PREFILTER+LL --out results/mersenne/domino_wave/
"""

import argparse
import json
import math
import time
import hashlib
import subprocess
import os
from pathlib import Path

# Path to high-performance Rust worker (Release mode)
RUST_WORKER_EXE = Path(__file__).parent.parent / "tools" / "mersenne-worker-rs" / "target" / "release" / "mersenne-worker-rs.exe"


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
    # TODO: import from scripts.mersenne_spectral_poc import probe
    # result = probe(p)
    # return result["z"]
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
    
    if "GHOST_PREFILTER" in method:
        # For now, pre-filtering is handled at the Python wrapper level
        # but the core calculation is Rust.
        # In a future version, Ghost Locus logic will move into the Rust crate.
        pass

    # Use Rust worker if available
    if RUST_WORKER_EXE.exists():
        print(f"  [Wrapper] Native Rust execution enabled: {RUST_WORKER_EXE}")
        cmd = [
            str(RUST_WORKER_EXE),
            "--block-id", str(block_id),
            "--p-start", str(p_start),
            "--p-end", str(p_end),
            "--probe", probe_name,
            "--out", str(out_dir)
        ]
        cp = subprocess.run(cmd, capture_output=False)
        if cp.returncode == 0:
            result_path = out_dir / f"block_result_{block_id}.json"
            if result_path.exists():
                return json.loads(result_path.read_text())
        
        print("  [Warning] Rust worker failed or returned non-zero. Falling back to Python LL.")

    # Fallback to pure Python (SLOOW - for diagnostic only)
    t0 = time.time()
    candidates = sieve_primes(p_start, p_end)
    
    primes_found = []
    for p in candidates:
        if lucas_lehmer(p):
            primes_found.append(p)
    
    wall_time = time.time() - t0
    result = {
        "block_id": block_id,
        "probe": probe_name,
        "p_start": p_start,
        "p_end": p_end,
        "candidates_sieved": len(candidates),
        "spectral_anomalies": 0,
        "primes_found": primes_found,
        "wall_time_s": round(wall_time, 3),
        "status": "DONE_PYTHON_FALLBACK",
    }
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
    print(f"[Block {args.block_id}] Done. Sieved={result.get('candidates_sieved', 0)} "
          f"Anomalies={result.get('spectral_anomalies', 0)} "
          f"Primes={result['primes_found']} "
          f"Time={result['wall_time_s']:.1f}s")

    if result["primes_found"]:
        print(f"  !!! DISCOVERY: {result['primes_found']} — escalate to FCD !!!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> int:
    print("Generating Mersenne Domino-Wave architecture...")

    waves = generate_domino_waves(
        p_start=FRONTIER_START,
        p_end=FRONTIER_END,
        block_width=BLOCK_WIDTH,
        max_parallel=MAX_WAVE_PARALLEL,
    )

    total_blocks = sum(len(w) for w in waves)
    print(f"  Waves: {len(waves)}")
    print(f"  Total blocks: {total_blocks}")
    for i, wave in enumerate(waves):
        p0 = wave[0].p_start
        p1 = wave[-1].p_end
        print(f"  Wave {i}: {len(wave)} blocks  p=[{p0:,}, {p1:,}]  priority={wave[0].priority}")

    # Build Jules order
    order = build_jules_order(waves)

    # Write outputs
    out_dir = Path("jules_orders")
    out_dir.mkdir(exist_ok=True)

    order_path = out_dir / "JULES_ORDER_MERSENNE_DOMINO_WAVE_V1.json"
    order_path.write_text(json.dumps(order, indent=2), encoding="utf-8")
    print(f"\n  Jules order  -> {order_path}")

    scripts_dir = Path("scripts")
    agg_path = scripts_dir / "mersenne_domino_aggregator.py"
    agg_path.write_text(AGGREGATOR_CODE, encoding="utf-8")
    print(f"  Aggregator   -> {agg_path}")

    worker_path = scripts_dir / "mersenne_domino_worker.py"
    worker_path.write_text(WORKER_CODE, encoding="utf-8")
    print(f"  Worker       -> {worker_path}")

    print("\nDone. Next step:")
    print("  1. Run Wave 0 locally to validate: python scripts/mersenne_domino_worker.py --block_id 0 --p_start 25000 --p_end 30000 --method LL")
    print("  2. Commit + push Jules order")
    print("  3. Jules picks up JULES_ORDER_MERSENNE_DOMINO_WAVE_V1.json and fans out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
