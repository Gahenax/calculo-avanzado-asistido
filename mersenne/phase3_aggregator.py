"""
phase3_aggregator.py
====================
Gate 0: integrity check + aggregation of Phase-3 block shards.

Usage:
  python scripts/phase3_aggregator.py [--shard-dir DIR] [--out-dir DIR]

Reads:
  results/riemann/phase3/gammas_block_{id}.npy      (from Jules)
  results/riemann/phase3/manifest_block_{id}.json

Produces:
  results/riemann/RIEMANN_GAMMAS_PHASE3.npy
  results/riemann/PHASE3_MANIFEST.json
  results/riemann/PHASE3_INTEGRITY_REPORT.json

Also runs Gate-1 (sanity) if N >= 2000, so early abort is possible
after just 4-5 blocks.
"""
from __future__ import annotations

import sys
import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import argparse
import hashlib
import json
import math
import os
import time
import numpy as np

PROJECT    = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis"
SHARD_DIR  = os.path.join(PROJECT, "results", "riemann", "phase3")
OUT_DIR    = os.path.join(PROJECT, "results", "riemann")
ORDER_FILE = os.path.join(PROJECT, "jules_orders", "JULES_ORDER_RIEMANN_P3.json")

N_TARGET = 10_000
EARLY_GATE1_N = 2_000   # run sanity check as soon as we have this many
GATE1_PRIMES  = [2, 3, 5, 7, 11, 13, 17, 19]
GATE1_Z_MIN   = 1.5
GATE1_MIN_PASS = 4   # out of 8


# ─── Hashing ──────────────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_array(arr: np.ndarray) -> str:
    return hashlib.sha256(arr.tobytes()).hexdigest()


# ─── Block loading ────────────────────────────────────────────────────────────

def load_block(shard_dir: str, block_id: int) -> tuple[np.ndarray | None, dict | None]:
    gamma_path    = os.path.join(shard_dir, f"gammas_block_{block_id}.npy")
    manifest_path = os.path.join(shard_dir, f"manifest_block_{block_id}.json")

    if not os.path.exists(gamma_path):
        return None, None
    if not os.path.exists(manifest_path):
        return None, None

    gammas   = np.load(gamma_path)
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())

    # Verify checksum if present
    computed_hash = sha256_file(gamma_path)
    stored_hash   = manifest.get("sha256_npy", "")
    if stored_hash and computed_hash != stored_hash:
        print(f"  [WARN] Block {block_id}: sha256 mismatch! Stored={stored_hash[:16]}... Got={computed_hash[:16]}...")

    return gammas, manifest


# ─── Gate 0: Integrity checks ─────────────────────────────────────────────────

def gate0_check(gammas: np.ndarray, manifests: list[dict], blocks_loaded: list[int]) -> dict:
    """
    Gate 0 checks (must all pass before spectral analysis):
      G0.1  Monotonicity
      G0.2  No duplicate zeros (within 1e-6)
      G0.3  Mean gap within 20% of theoretical
      G0.4  N >= N_TARGET
    """
    report = {"checks": {}, "passed": False}

    # G0.1 Monotonicity
    diffs = np.diff(gammas)
    mono_ok = bool(np.all(diffs > 0))
    n_inversions = int(np.sum(diffs <= 0))
    report["checks"]["G0.1_monotonicity"] = {
        "ok": mono_ok, "n_inversions": n_inversions
    }

    # G0.2 No duplicates
    dupes = int(np.sum(diffs < 1e-6))
    report["checks"]["G0.2_no_duplicates"] = {
        "ok": dupes == 0, "n_near_duplicates": dupes
    }

    # G0.3 Mean gap theoretical
    T_mid  = float(gammas[len(gammas)//2])
    gap_th = 2 * math.pi / math.log(T_mid)  # mean spacing ~ 2pi/log(T)
    gap_ob = float(np.mean(diffs))
    gap_ratio = gap_ob / gap_th
    gap_ok = 0.80 <= gap_ratio <= 1.20
    report["checks"]["G0.3_gap_density"] = {
        "ok": gap_ok,
        "theoretical": round(gap_th, 6),
        "observed": round(gap_ob, 6),
        "ratio": round(gap_ratio, 4)
    }

    # G0.4 N
    N = len(gammas)
    report["checks"]["G0.4_N_target"] = {
        "ok": N >= N_TARGET,
        "N": N,
        "target": N_TARGET
    }

    all_ok = all(v["ok"] for v in report["checks"].values())
    report["passed"] = all_ok
    report["N_total"] = N
    report["blocks_loaded"] = blocks_loaded
    report["sha256_all"] = sha256_array(gammas)
    return report


# ─── Gate 1: Sanity (Layer A+) ────────────────────────────────────────────────

def _hann_window(gammas: np.ndarray, T0: float, T1: float) -> tuple[np.ndarray, np.ndarray]:
    mask = (gammas >= T0) & (gammas <= T1)
    g = gammas[mask]
    if g.size == 0:
        return g, np.array([])
    x = (g - T0) / (T1 - T0 + 1e-30)
    w = 0.5 * (1.0 - np.cos(2.0 * math.pi * x))
    return g, w


def S_abs(gammas: np.ndarray, u: float, T0: float, T1: float) -> float:
    g, w = _hann_window(gammas, T0, T1)
    if g.size == 0:
        return 0.0
    denom = math.sqrt(float(np.sum(w**2))) + 1e-30
    return float(abs((w * np.exp(1j * g * u)).sum() / denom))


def phase_null(gammas: np.ndarray, u: float, T0: float, T1: float,
               B: int = 300, seed: int = 0) -> np.ndarray:
    g, w = _hann_window(gammas, T0, T1)
    if g.size < 5:
        return np.zeros(B)
    denom = math.sqrt(float(np.sum(w**2))) + 1e-30
    rng   = np.random.default_rng(seed)
    vals  = np.array([
        float(abs((w * np.exp(1j * rng.uniform(0, 2*math.pi, g.size))).sum() / denom))
        for _ in range(B)
    ])
    return vals


def gate1_sanity(gammas: np.ndarray, T0: float, T1: float, label: str = "") -> dict:
    report = {"label": label, "probes": {}, "passed": False}
    n_pass = 0

    print(f"\n  [Gate 1{' '+label if label else ''}]  N={len(gammas)}  "
          f"T=[{T0:.1f},{T1:.1f}]")
    print(f"  {'Prime p':<10} {'u=log(p)':>10}  {'|S|':>7}  {'null_mu':>7}  {'z':>6}  status")
    print(f"  {'-'*55}")

    for p in GATE1_PRIMES:
        u     = math.log(p)
        obs   = S_abs(gammas, u, T0, T1)
        null  = phase_null(gammas, u, T0, T1, B=200, seed=p)
        mu    = float(null.mean())
        sigma = float(null.std()) + 1e-30
        z     = (obs - mu) / sigma
        ok    = z > GATE1_Z_MIN
        if ok:
            n_pass += 1
        flag = "PASS" if ok else "    "
        print(f"  p={p:<9} {u:>10.4f}  {obs:>7.4f}  {mu:>7.4f}  {z:>6.2f}  {flag}")
        report["probes"][p] = {"z": round(z, 3), "ok": ok}

    gate_ok = n_pass >= GATE1_MIN_PASS
    report["n_pass"] = n_pass
    report["passed"] = gate_ok
    status = "PASS" if gate_ok else "FAIL (instrument unreliable)"
    print(f"\n  Gate 1: {n_pass}/{len(GATE1_PRIMES)} primes detected  --> {status}")
    return report


# ─── Aggregator main ──────────────────────────────────────────────────────────

def aggregate(shard_dir: str, out_dir: str, order_file: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    print("="*70)
    print("  PHASE-3 AGGREGATOR + GATE 0")
    print(f"  Shard dir: {shard_dir}")
    print("="*70)

    # Load work order
    with open(order_file, encoding="utf-8") as f:
        order = json.load(f)
    blocks_spec = order["block_design"]["blocks"]

    # ── Load all available blocks ─────────────────────────────────────────────
    all_gammas   = []
    all_manifests = []
    blocks_loaded = []
    blocks_missing = []

    print(f"\n  {'Block':<8} {'Probe':<10} {'T range':<22} {'N_found':>8}  status")
    print(f"  {'-'*60}")

    for spec in blocks_spec:
        bid     = spec["id"]
        gammas_b, manifest_b = load_block(shard_dir, bid)
        if gammas_b is None:
            blocks_missing.append(bid)
            print(f"  {bid:<8} {spec['probe']:<10} "
                  f"[{spec['T0']:.0f},{spec['T1']:.0f}]  {'---':>8}  MISSING")
            continue

        N_b = len(gammas_b)
        all_gammas.append(gammas_b)
        all_manifests.append(manifest_b)
        blocks_loaded.append(bid)
        print(f"  {bid:<8} {spec['probe']:<10} "
              f"[{spec['T0']:.0f},{spec['T1']:.0f}]  {N_b:>8}  OK")

    if not all_gammas:
        print("\n  [ERROR] No blocks found. Run Jules Phase-3 first.")
        print(f"  Expected shards in: {shard_dir}")
        _generate_local_demo(shard_dir, blocks_spec[:5])
        print("\n  Generated 5 demo blocks via mpmath. Re-run aggregator.")
        return

    # Concatenate and sort
    gammas_all = np.sort(np.concatenate(all_gammas))
    N_total    = len(gammas_all)
    print(f"\n  Loaded {len(blocks_loaded)} blocks | "
          f"Missing {len(blocks_missing)} | N_total = {N_total}")

    # ── Gate 0 ────────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("  GATE 0 — INTEGRITY")
    print("="*70)
    g0 = gate0_check(gammas_all, all_manifests, blocks_loaded)
    for name, result in g0["checks"].items():
        icon = "[OK]" if result["ok"] else "[!!]"
        print(f"  {icon} {name}: {result}")
    print(f"\n  Gate 0: {'PASS' if g0['passed'] else 'FAIL'}")

    # ── Early Gate 1 (if N >= threshold) ─────────────────────────────────────
    if N_total >= EARLY_GATE1_N:
        T0_all = float(gammas_all[0])
        T1_all = float(gammas_all[-1])
        g1 = gate1_sanity(gammas_all, T0_all, T1_all, label="early")

        if not g1["passed"] and N_total < N_TARGET:
            print("\n  [EARLY ABORT] Gate 1 failed with partial data.")
            print("  Possible pipeline issue. Check zero precision and method.")
    else:
        g1 = {"passed": None, "note": f"Skipped (N={N_total} < {EARLY_GATE1_N})"}
        print(f"\n  [Gate 1] Skipped — N={N_total} < {EARLY_GATE1_N}")

    # ── Save outputs ──────────────────────────────────────────────────────────
    if N_total > 0:
        out_npy = os.path.join(out_dir, "RIEMANN_GAMMAS_PHASE3.npy")
        np.save(out_npy, gammas_all)

        phase3_manifest = {
            "order_id":       order["order_id"],
            "T_start":        float(gammas_all[0]),
            "T_end":          float(gammas_all[-1]),
            "N_total":        N_total,
            "N_target":       N_TARGET,
            "target_reached": N_total >= N_TARGET,
            "blocks_loaded":  blocks_loaded,
            "blocks_missing": blocks_missing,
            "sha256_gammas":  sha256_array(gammas_all),
            "sha256_npy":     sha256_file(out_npy),
            "mean_gap":       float(np.mean(np.diff(gammas_all))),
            "created":        time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(os.path.join(out_dir, "PHASE3_MANIFEST.json"), "w") as f:
            json.dump(phase3_manifest, f, indent=2)

        integrity_report = {
            "gate0": g0,
            "gate1_early": g1,
            "status": "READY_FOR_SPECTRAL" if (g0["passed"] and
                      (g1.get("passed") or g1.get("passed") is None)) else "NEEDS_REVIEW"
        }
        with open(os.path.join(out_dir, "PHASE3_INTEGRITY_REPORT.json"), "w") as f:
            json.dump(integrity_report, f, indent=2)

        print(f"\n  Saved: {out_npy}")
        print(f"  Status: {integrity_report['status']}")
    else:
        print("\n  No data to save.")


def _generate_local_demo(shard_dir: str, specs: list[dict]) -> None:
    """Generate demo blocks via mpmath for testing the pipeline locally."""
    os.makedirs(shard_dir, exist_ok=True)
    try:
        import mpmath
        mpmath.mp.dps = 25
    except ImportError:
        print("  mpmath not available for demo generation.")
        return

    import hashlib
    import time as _time
    for spec in specs:
        bid = spec["id"]
        T0, T1 = spec["T0"], spec["T1"]
        print(f"  Generating demo block {bid} T=[{T0},{T1}]...", end="", flush=True)

        def N_approx(T):
            return (T/(2*math.pi)) * math.log(T/(2*math.pi)) - T/(2*math.pi)

        n = max(1, int(N_approx(T0)) - 3)
        zeros = []
        t0_wall = _time.time()
        while True:
            z = float(mpmath.im(mpmath.zetazero(n)))
            if z > T1 + 1: break
            if T0 <= z <= T1: zeros.append(z)
            n += 1
            if len(zeros) >= 600 or n > int(N_approx(T0)) + 1000: break

        gammas = np.array(sorted(zeros), dtype=np.float64)
        npy_path = os.path.join(shard_dir, f"gammas_block_{bid}.npy")
        np.save(npy_path, gammas)

        sha = hashlib.sha256(open(npy_path,"rb").read()).hexdigest()
        manifest = {
            "block_id": bid, "probe": spec["probe"],
            "T0": T0, "T1": T1,
            "N_found": len(gammas),
            "gamma_min": float(gammas[0]) if len(gammas) else 0.0,
            "gamma_max": float(gammas[-1]) if len(gammas) else 0.0,
            "mean_gap": float(np.mean(np.diff(gammas))) if len(gammas) > 1 else 0.0,
            "sha256_npy": sha,
            "method": "mpmath.zetazero dps=25",
            "precision_dps": 25,
            "wall_time_s": round(_time.time() - t0_wall, 2),
            "status": "OK"
        }
        with open(os.path.join(shard_dir, f"manifest_block_{bid}.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        print(f" {len(gammas)} zeros  sha={sha[:12]}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-dir", default=SHARD_DIR)
    parser.add_argument("--out-dir",   default=OUT_DIR)
    parser.add_argument("--order",     default=ORDER_FILE)
    parser.add_argument("--demo",      action="store_true",
                        help="Generate demo blocks 0-4 via mpmath and aggregate")
    args = parser.parse_args()

    if args.demo:
        with open(args.order, encoding="utf-8") as f:
            order = json.load(f)
        _generate_local_demo(args.shard_dir, order["block_design"]["blocks"][:5])

    aggregate(args.shard_dir, args.out_dir, args.order)
