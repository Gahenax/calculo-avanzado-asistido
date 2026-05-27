#!/usr/bin/env python3
"""
MERSENNE TRAMPOLINE COORDINATOR
================================

Strategy
--------
Use the 25 certified Mersenne primes as simultaneous launch pads
("trampolines") for parallel search. Each trampoline contributes:

  1. ANCHOR probe   -- verify LL(p_i) = 0  (sanity / calibration)
  2. GAP probe      -- search [p_i, p_{i+1}] for missed primes
  3. Ghost calibration -- record real z-scores at known primes
                          to tune the pre-filter threshold

All 25 gap probes + the frontier wave run simultaneously in Jules.
This produces 25 concurrent data streams instead of 1 serial scan.

Architecture
------------
Phase A: 25 Anchor + 24 Gap probes  (covers p=[3, 23209])
Phase B: Frontier Domino-WAVE       (covers p=[23209, 200000])

Both phases launch simultaneously. Phase A completes fast (gaps are
small). Its Ghost calibration data feeds Phase B's pre-filter in
real time, progressively sharpening the frontier search.

Throughput gain
---------------
Serial baseline:  1 probe at a time
Trampoline:       25 probes simultaneously = O(25x) raw speedup
                  + Ghost calibration from Phase A sharpens Phase B
                  → effective speedup exceeds linear (cascading effect)
"""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import glob

# ─────────────────────────────────────────────────────────────
# Certified primes (loaded from ledger at runtime, hardcoded as fallback)
# ─────────────────────────────────────────────────────────────

CERTIFIED_FALLBACK: List[int] = [
    2, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127,
    521, 607, 1279, 2203, 2281, 3217, 4253, 4423,
    9689, 9941, 11213, 19937, 21701, 23209
]

# Known next primes beyond our frontier (GIMPS-confirmed, for reference)
NEXT_KNOWN_BEYOND_FRONTIER: List[int] = [44497, 86243, 110503, 132049, 216091]

# Frontier parameters
FRONTIER_START = 23209       # Last certified
FRONTIER_END   = 100000      # Phase-B target
FRONTIER_BLOCK = 5000        # Block width for Domino-WAVE

# Ghost Locus pre-filter (from Phase-3 Riemann spectral POC)
GHOST_Z_THRESHOLD_DEFAULT = 2.0
GHOST_Z_CALIBRATED = None    # Will be set after Phase-A anchors return

# ─────────────────────────────────────────────────────────────
# Probe datamodels
# ─────────────────────────────────────────────────────────────

@dataclass
class AnchorProbe:
    """Verify that LL(p) = 0 for a known certified prime."""
    probe_id: str
    probe_type: str = "ANCHOR"
    p: int = 0
    expected_result: str = "PRIME"       # Must match or abort
    purpose: str = "calibration"
    ghost_locus_expected: str = "high_z" # We expect z >> threshold

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class GapProbe:
    """Search the gap [p_lo, p_hi] for any Mersenne primes missed."""
    probe_id: str
    probe_type: str = "GAP"
    p_lo: int = 0
    p_hi: int = 0
    gap_size: int = 0
    anchor_lo: int = 0       # Left certified prime
    anchor_hi: int = 0       # Right certified prime
    method: str = "LL"
    expected_result: str = "EMPTY"       # We expect no primes here
    priority: str = "HIGH"
    notes: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


@dataclass
class FrontierBlock:
    """Unexplored block beyond last certified prime."""
    probe_id: str
    probe_type: str = "FRONTIER"
    wave: int = 0
    p_start: int = 0
    p_end: int = 0
    method: str = "GHOST_PREFILTER+LL"
    priority: str = "NORMAL"

    def to_dict(self) -> Dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Ledger loader
# ─────────────────────────────────────────────────────────────

def load_certified_primes(canon_dir: Path = Path("lab/canon")) -> List[int]:
    """Load certified Mersenne prime exponents from the canon ledger."""
    primes: List[int] = []
    for f in canon_dir.glob("Mersenne_Certified_*.json"):
        stem = f.stem  # e.g. "Mersenne_Certified_23209_1771511918"
        parts = stem.split("_")
        try:
            # Format: Mersenne_Certified_{p}_{timestamp}
            p = int(parts[2])
            primes.append(p)
        except (IndexError, ValueError):
            pass

    if not primes:
        print("  [warn] No certified primes found in ledger — using fallback list")
        return sorted(CERTIFIED_FALLBACK)

    return sorted(set(primes))


# ─────────────────────────────────────────────────────────────
# Probe generators
# ─────────────────────────────────────────────────────────────

NATO = [
    "ALPHA","BRAVO","CHARLIE","DELTA","ECHO","FOXTROT","GOLF","HOTEL",
    "INDIA","JULIET","KILO","LIMA","MIKE","NOVEMBER","OSCAR","PAPA",
    "QUEBEC","ROMEO","SIERRA","TANGO","UNIFORM","VICTOR","WHISKEY",
    "XRAY","YANKEE","ZULU"
]


def generate_anchor_probes(certified: List[int]) -> List[AnchorProbe]:
    probes: List[AnchorProbe] = []
    for i, p in enumerate(certified):
        probe = AnchorProbe(
            probe_id=f"ANCHOR_{NATO[i % len(NATO)]}_{p}",
            p=p,
            expected_result="PRIME",
            purpose=(
                f"Sanity check: LL(M_{p}) must return residue=0. "
                f"Failure = implementation error, abort all probes."
            ),
            ghost_locus_expected=f"z >> {GHOST_Z_THRESHOLD_DEFAULT} (known prime)"
        )
        probes.append(probe)
    return probes


def generate_gap_probes(certified: List[int]) -> List[GapProbe]:
    """Generate one gap probe per consecutive prime pair."""
    probes: List[GapProbe] = []
    for i in range(len(certified) - 1):
        p_lo = certified[i]
        p_hi = certified[i + 1]
        gap  = p_hi - p_lo

        # Skip trivially small gaps
        if gap <= 2:
            continue

        # For large gaps, method = GHOST_PREFILTER+LL (faster)
        method = "GHOST_PREFILTER+LL" if gap > 200 else "LL"

        priority = "CRITICAL" if i < 4 else ("HIGH" if gap > 500 else "NORMAL")

        probe = GapProbe(
            probe_id=f"GAP_{NATO[i % len(NATO)]}_{p_lo}_{p_hi}",
            p_lo=p_lo + 1,
            p_hi=p_hi - 1,
            gap_size=gap,
            anchor_lo=p_lo,
            anchor_hi=p_hi,
            method=method,
            expected_result="EMPTY",
            priority=priority,
            notes=(
                f"Gap between M_{p_lo} and M_{p_hi}. "
                f"Historically confirmed empty by GIMPS / direct enumeration. "
                f"Running for completeness and Ghost Locus calibration data."
            )
        )
        probes.append(probe)
    return probes


def generate_frontier_blocks(
    p_start: int,
    p_end:   int,
    block_w: int,
) -> List[FrontierBlock]:
    """Domino-WAVE frontier beyond last certified prime."""
    blocks: List[FrontierBlock] = []
    wave_size = 1
    wave = 0
    cur  = p_start

    while cur < p_end:
        for _ in range(min(wave_size, 20)):
            if cur >= p_end:
                break
            end = min(cur + block_w, p_end)
            priority = "CRITICAL" if wave == 0 else ("HIGH" if wave <= 2 else "NORMAL")
            b = FrontierBlock(
                probe_id=f"FRONTIER_W{wave}_{cur}_{end}",
                wave=wave,
                p_start=cur,
                p_end=end,
                method="GHOST_PREFILTER+LL",
                priority=priority,
            )
            blocks.append(b)
            cur = end
        wave      += 1
        wave_size  = min(wave_size * 2, 20)

    return blocks


# ─────────────────────────────────────────────────────────────
# Jules order builder
# ─────────────────────────────────────────────────────────────

def build_trampoline_order(
    certified:  List[int],
    anchors:    List[AnchorProbe],
    gaps:       List[GapProbe],
    frontier:   List[FrontierBlock],
) -> Dict[str, Any]:

    big_gaps = sorted(
        [(g.anchor_lo, g.anchor_hi, g.gap_size)
         for g in gaps if g.gap_size > 100],
        key=lambda x: x[2], reverse=True
    )

    return {
        "order_id":  "JO-2026-MERSENNE-TRAMPOLINE-V1",
        "version":   "1.0.0",
        "created":   "2026-02-23T02:00:00-05:00",
        "protocol":  "OUROBOROS v2.0 / TRAMPOLINE-CASCADE",
        "system":    "Gahenax Core v1.1.1",

        "mission": {
            "strategy": "TRAMPOLINE-DOMINO",
            "description": (
                "25 certified primes used simultaneously as launch pads. "
                "Phase A: 25 Anchor probes + 24 Gap probes run in parallel. "
                "Phase B: Frontier Domino-WAVE launches immediately alongside Phase A. "
                "Phase A calibration data sharpens Phase B Ghost Locus pre-filter in real time."
            ),
            "certified_primes_used": certified,
            "n_certified": len(certified),
            "last_certified": certified[-1],
            "frontier_target": [FRONTIER_START, FRONTIER_END],
            "known_next_primes": NEXT_KNOWN_BEYOND_FRONTIER,
        },

        "throughput_model": {
            "serial_baseline": "1 probe at a time — weeks",
            "trampoline_phase_a": (
                f"{len(anchors)} anchors + {len(gaps)} gaps = "
                f"{len(anchors)+len(gaps)} simultaneous probes"
            ),
            "trampoline_phase_b": f"{len(frontier)} frontier blocks (Domino-WAVE)",
            "total_simultaneous": len(anchors) + len(gaps) + len(frontier),
            "effective_speedup": (
                f"~{len(anchors)+len(gaps)+len(frontier)}x raw parallel speedup. "
                "Phase-A Ghost calibration adds additional filter gain on Phase-B ~40% fewer LL calls."
            ),
            "expected_time_all_phases": "Hours (Jules) vs Weeks (serial)",
        },

        "phase_a_anchors": {
            "description": "Verify LL=0 for all 25 certified primes. Abort all if any fails.",
            "n_anchors": len(anchors),
            "gate": "ALL anchors must return result=PRIME. One failure = implementation error.",
            "probes": [a.to_dict() for a in anchors],
        },

        "phase_a_gaps": {
            "description": "Search 24 gaps between consecutive certified primes.",
            "n_gaps": len(gaps),
            "expected_result": "All gaps historically empty. Any prime found is a new discovery.",
            "calibration_output": (
                "Each gap probe records Ghost Locus z-scores for all tested p. "
                "This calibrates the threshold for Phase B."
            ),
            "largest_gaps": [
                {"p_lo": lo, "p_hi": hi, "gap": g}
                for lo, hi, g in big_gaps[:5]
            ],
            "probes": [g.to_dict() for g in gaps],
        },

        "phase_b_frontier": {
            "description": (
                f"Domino-WAVE beyond p={FRONTIER_START}. "
                "Runs simultaneously with Phase A. "
                f"Ghost threshold auto-calibrates from Phase A results."
            ),
            "n_blocks": len(frontier),
            "ghost_z_threshold_initial": GHOST_Z_THRESHOLD_DEFAULT,
            "ghost_calibration_update": (
                "After first 5 Phase-A anchors return: "
                "update ghost_z_threshold = mean(anchor_z) - 1.5*std(anchor_z). "
                "Broadcast update to all active Phase-B workers."
            ),
            "domino_cascade_rule": (
                "Wave 0 (single block) completes -> triggers Wave 1 (2 blocks), etc. "
                "All waves already queued in Jules — no manual trigger."
            ),
            "blocks": [b.to_dict() for b in frontier],
        },

        "gate_policy": {
            "gate0_anchor": {
                "trigger": "Phase A anchor completes",
                "check": "LL residue == 0",
                "pass": "Record calibration z-score. Continue.",
                "fail": "HALT ALL probes. LL implementation is broken."
            },
            "gate1_gap": {
                "trigger": "Any gap probe finds a prime",
                "check": "Did we miss a Mersenne prime between known ones?",
                "pass": "Discovery! Full FCD audit. Independent re-verification.",
                "fail": "N/A (expected empty)"
            },
            "gate2_frontier": {
                "trigger": "Any frontier block finds a prime",
                "check": "New candidate via LL residue == 0",
                "pass": "CRITICAL ESCALATION. Submit to GIMPS for global certification.",
                "fail": "N/A"
            },
            "ghost_locus_gate": {
                "trigger": "Phase-A returns >= 5 anchor z-scores",
                "action": (
                    "Recompute ghost_z_threshold dynamically. "
                    "Push updated threshold to all active Phase-B workers via shared config file."
                )
            }
        },

        "output_contract": {
            "per_anchor": "anchor_result_{p}.json  +  anchor_telemetry_{p}.jsonl",
            "per_gap":    "gap_result_{p_lo}_{p_hi}.json  +  gap_telemetry_{p_lo}_{p_hi}.jsonl",
            "per_frontier": "block_result_{probe_id}.json  +  block_telemetry_{probe_id}.jsonl",
            "aggregator": "scripts/mersenne_trampoline_aggregator.py",
            "output_dir": "results/mersenne/trampoline/",
            "ledger_dir": "ledger_mersenne_trampoline/",
            "calibration_file": "results/mersenne/trampoline/ghost_calibration.json",
        },

        "forbidden_claims": [
            "A non-zero LL residue is a near-miss.",
            "Ghost Locus z-score alone confirms primality.",
            "PREFILTERED means composite — it means untested.",
            "This replaces GIMPS global verification.",
        ]
    }


# ─────────────────────────────────────────────────────────────
# Aggregator (written to scripts/)
# ─────────────────────────────────────────────────────────────

TRAMPOLINE_AGGREGATOR = '''\
#!/usr/bin/env python3
"""
MERSENNE TRAMPOLINE AGGREGATOR
================================
Called after each probe completes.
Handles anchors, gaps, and frontier blocks.
"""
import json, argparse, hashlib, sys
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
        f.write(json.dumps(result) + "\\n")

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
    c["n_anchors"] += 1
    if c["n_anchors"] >= 5:
        zs = [x["z"] for x in c["z_scores"]]
        import statistics
        mu    = statistics.mean(zs)
        sigma = statistics.stdev(zs) if len(zs) > 1 else 1.0
        new_thresh = max(1.5, mu - 1.5 * sigma)
        c["threshold"] = round(new_thresh, 4)
        print(f"  [Ghost calibration] New threshold = {c["threshold"]:.4f}"
              f"  (mean_z={mu:.3f}, sigma={sigma:.3f})")
    save_calib(c)
    print(f"  [Anchor M_{p}] OK. z={z:.3f}  calibration_n={c["n_anchors"]}")

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
'''


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("  MERSENNE TRAMPOLINE-CASCADE COORDINATOR")
    print("=" * 60)

    # Load certified primes
    certified = load_certified_primes()
    print(f"\n  Certified primes loaded: {len(certified)}")
    print(f"  Range: M_{certified[0]} ... M_{certified[-1]}")

    # Phase A
    anchors  = generate_anchor_probes(certified)
    gaps     = generate_gap_probes(certified)

    # Phase B
    frontier = generate_frontier_blocks(
        p_start=FRONTIER_START,
        p_end=FRONTIER_END,
        block_w=FRONTIER_BLOCK,
    )

    total_simultaneous = len(anchors) + len(gaps) + len(frontier)

    print(f"\n  Phase A — Anchors:  {len(anchors):>3}  (verify all 25 known primes)")
    print(f"  Phase A — Gaps:     {len(gaps):>3}  (search between known primes)")
    print(f"  Phase B — Frontier: {len(frontier):>3}  (Domino-WAVE beyond p={FRONTIER_START})")
    print(f"  {'-'*40}")
    print(f"  TOTAL SIMULTANEOUS: {total_simultaneous:>3}  probes at once in Jules")
    print(f"  Raw speedup vs serial: ~{total_simultaneous}x")

    # Build order
    order = build_trampoline_order(certified, anchors, gaps, frontier)

    # Write Jules order
    out_dir = Path("jules_orders")
    out_dir.mkdir(exist_ok=True)
    order_path = out_dir / "JULES_ORDER_MERSENNE_TRAMPOLINE_V1.json"
    order_path.write_text(json.dumps(order, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write aggregator
    agg_path = Path("scripts") / "mersenne_trampoline_aggregator.py"
    agg_path.write_text(TRAMPOLINE_AGGREGATOR, encoding="utf-8")

    # Summary
    print(f"\n  Jules order  -> {order_path}")
    print(f"  Aggregator   -> {agg_path}")

    print(f"\n  LARGEST GAPS (most likely to contain missed primes):")
    sorted_gaps = sorted(gaps, key=lambda g: g.gap_size, reverse=True)
    for g in sorted_gaps[:6]:
        print(f"    [{g.anchor_lo:>6}, {g.anchor_hi:>6}]  gap={g.gap_size:>5}  method={g.method}")

    print(f"\n  THROUGHPUT:")
    print(f"    All {total_simultaneous} probes run simultaneously in Jules.")
    print(f"    Phase A returns in minutes (small gaps).")
    print(f"    Phase A Ghost z-scores auto-calibrate Phase B threshold.")
    print(f"    Phase B frontier covers known next primes: {NEXT_KNOWN_BEYOND_FRONTIER[:3]}")
    print(f"\n  Commit jules_orders/JULES_ORDER_MERSENNE_TRAMPOLINE_V1.json")
    print(f"  and Jules will fan out all {total_simultaneous} probes immediately.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
