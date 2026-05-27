"""
layer_c_adversarial.py
======================
Adversarial audit of Layer C anomalies: peaks at u = k*log(2) for k=10,11,29.

Protocol (from JULES_ORDER_RIEMANN_P3.json):
  - 3 sub-windows of the Phase-3 dataset (non-overlapping)
  - 2 window types: hann, tukey
  - 3 null methods: phase_randomization, block_permutation, gue_surrogate
  - Survival criterion: peak must survive >= 2/3 nulls in >= 2/3 windows

Inputs:
  results/riemann/RIEMANN_GAMMAS_PHASE3.npy  (from aggregator)
  OR
  results/riemann/jules_phase1_full.jsonl    (fallback: Phase-1 only)

Pre-registered parameters (not changed post-hoc):
  TARGET_K = [10, 11, 29]      -- k values flagged in Phase-1 Layer C
  N_WINDOWS = 3                -- non-overlapping T sub-windows
  NULLS = [phase_random, block_perm, gue_surrogate]
  Z_SURVIVE = 1.5
  B_NULL = 400
"""
from __future__ import annotations

import sys
import io
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import math
import os
import numpy as np

PROJECT    = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis"
PHASE3_NPY = os.path.join(PROJECT, "results", "riemann", "RIEMANN_GAMMAS_PHASE3.npy")
PHASE1_FP  = os.path.join(PROJECT, "results", "riemann", "jules_phase1_full.jsonl")

# ── Pre-registered ────────────────────────────────────────────────────────────
TARGET_K   = [10, 11, 29]          # anomalies flagged in Phase-1 Layer C
ALL_K      = list(range(1, 31))    # full k*log(2) grid for context
N_WINDOWS  = 3
Z_SURVIVE  = 1.5
B_NULL     = 400
SURVIVE_NULLS   = 2   # must survive >= 2/3 null methods
SURVIVE_WINDOWS = 2   # must survive >= 2/3 windows
LOG2 = math.log(2)
# ─────────────────────────────────────────────────────────────────────────────


# ─── Data ────────────────────────────────────────────────────────────────────

def load_gammas() -> np.ndarray:
    if os.path.exists(PHASE3_NPY):
        g = np.load(PHASE3_NPY)
        print(f"  Loaded Phase-3: N={len(g)}, T=[{g[0]:.1f},{g[-1]:.1f}]")
        return g

    print(f"  Phase-3 not found. Falling back to Phase-1...")
    zeros = []
    with open(PHASE1_FP, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            t = rec.get("t_est") or rec.get("payload", {}).get("t_est")
            if t and float(t) > 0:
                zeros.append(float(t))
    g = np.array(sorted(set(zeros)))
    print(f"  Loaded Phase-1 fallback: N={len(g)}, T=[{g[0]:.1f},{g[-1]:.1f}]")
    print(f"  [WARN] N={len(g)} is insufficient for high-power test.")
    print(f"  Results are exploratory only.")
    return g


# ─── Window functions ─────────────────────────────────────────────────────────

def window_weights(gammas: np.ndarray, T0: float, T1: float,
                   mode: str = "hann") -> tuple[np.ndarray, np.ndarray]:
    mask = (gammas >= T0) & (gammas <= T1)
    g = gammas[mask]
    if g.size == 0:
        return g, np.array([])
    x = (g - T0) / (T1 - T0 + 1e-30)
    if mode == "hann":
        w = 0.5 * (1.0 - np.cos(2.0 * math.pi * x))
    elif mode == "tukey":
        alpha = 0.2
        w = np.ones_like(x)
        left  = x < alpha/2
        right = x > 1 - alpha/2
        w[left]  = 0.5*(1 + np.cos(2*math.pi*(x[left]/alpha - 0.5)))
        w[right] = 0.5*(1 + np.cos(2*math.pi*((x[right]-1)/alpha + 0.5)))
    else:
        w = np.ones_like(g)
    return g, w


def S_obs(gammas, u, T0, T1, mode="hann"):
    g, w = window_weights(gammas, T0, T1, mode)
    if g.size < 5:
        return 0.0
    d = math.sqrt(float(np.sum(w**2))) + 1e-30
    return float(abs((w * np.exp(1j * g * u)).sum() / d))


# ─── Three null methods ───────────────────────────────────────────────────────

def null_phase_random(gammas, u, T0, T1, mode, B, seed):
    """Phase randomization: destroys all structure at u."""
    g, w = window_weights(gammas, T0, T1, mode)
    if g.size < 5:
        return np.zeros(B)
    d   = math.sqrt(float(np.sum(w**2))) + 1e-30
    rng = np.random.default_rng(seed)
    return np.array([
        float(abs((w * np.exp(1j * rng.uniform(0, 2*math.pi, g.size))).sum() / d))
        for _ in range(B)
    ])


def null_block_permutation(gammas, u, T0, T1, mode, B, seed, n_blocks=10):
    """
    Block permutation: permutes blocks of consecutive zeros.
    Preserves local density but destroys global phase coherence.
    """
    g, w = window_weights(gammas, T0, T1, mode)
    if g.size < 10:
        return np.zeros(B)
    d   = math.sqrt(float(np.sum(w**2))) + 1e-30
    rng = np.random.default_rng(seed)

    block_size = max(1, g.size // n_blocks)
    # Split into blocks of indices
    idx = np.arange(g.size)
    splits = [idx[i*block_size:(i+1)*block_size] for i in range(n_blocks)]
    # Last partial block
    rest = idx[n_blocks*block_size:]
    if len(rest) > 0:
        splits.append(rest)

    vals = np.empty(B)
    for b in range(B):
        perm    = rng.permutation(len(splits))
        idx_new = np.concatenate([splits[i] for i in perm])
        g_perm  = g[idx_new]
        w_perm  = w  # keep weights in original order
        S = (w_perm * np.exp(1j * g_perm * u)).sum() / d
        vals[b] = abs(S)
    return vals


def null_gue_surrogate(gammas, u, T0, T1, mode, B, seed):
    """
    GUE surrogate: replace zeros with GUE-distributed spacing sequence.
    Mean and total length matched to observed gammas.
    Destroys arithmetic structure while preserving spectral density.
    """
    g, w = window_weights(gammas, T0, T1, mode)
    if g.size < 5:
        return np.zeros(B)
    d    = math.sqrt(float(np.sum(w**2))) + 1e-30
    N    = g.size
    mean_gap = float(np.mean(np.diff(g))) if N > 1 else 1.0
    rng  = np.random.default_rng(seed)

    def gue_spacing(n, rng):
        """Wigner surmise approximation: p(s) ~ (pi/2)*s*exp(-pi*s^2/4)"""
        # Inverse CDF via rejection: use Rayleigh(sqrt(2/pi)) as proposal
        s = rng.rayleigh(scale=math.sqrt(2.0/math.pi), size=n)
        return s

    vals = np.empty(B)
    for b in range(B):
        spacings = gue_spacing(N-1, rng) * mean_gap
        spacings = np.maximum(spacings, 1e-6)
        g_surr   = T0 + np.concatenate([[0], np.cumsum(spacings)])[:N]

        # Recompute window for surrogate
        x_s = (g_surr - T0) / (T1 - T0 + 1e-30)
        if mode == "hann":
            w_s = 0.5 * (1.0 - np.cos(2.0 * math.pi * np.clip(x_s, 0, 1)))
        else:
            w_s = np.ones(N)
        d_s = math.sqrt(float(np.sum(w_s**2))) + 1e-30
        S   = (w_s * np.exp(1j * g_surr * u)).sum() / d_s
        vals[b] = abs(S)
    return vals


NULL_METHODS = {
    "phase_random":    null_phase_random,
    "block_perm":      null_block_permutation,
    "gue_surrogate":   null_gue_surrogate,
}


# ─── Single probe ────────────────────────────────────────────────────────────

def probe_adversarial(gammas: np.ndarray, k: int, T0: float, T1: float,
                      win_id: int, mode: str = "hann") -> dict:
    u   = k * LOG2
    obs = S_obs(gammas, u, T0, T1, mode)
    results = {"k": k, "u": u, "obs": obs, "window_id": win_id,
               "win_mode": mode, "T0": T0, "T1": T1}
    nulls_survived = 0

    for null_name, null_fn in NULL_METHODS.items():
        seed = k * 100 + win_id * 10 + list(NULL_METHODS).index(null_name)
        nv   = null_fn(gammas, u, T0, T1, mode, B_NULL, seed)
        mu   = float(nv.mean())
        sd   = float(nv.std()) + 1e-30
        z    = (obs - mu) / sd
        survives = z > Z_SURVIVE
        if survives:
            nulls_survived += 1
        results[null_name] = {"z": round(z, 3), "mu": round(mu, 4),
                               "sd": round(sd, 4), "survives": survives}

    results["nulls_survived"] = nulls_survived
    results["survives_null_criterion"] = nulls_survived >= SURVIVE_NULLS
    return results


# ─── Main ────────────────────────────────────────────────────────────────────

def run_adversarial_audit(gammas: np.ndarray) -> dict:
    T0_all = float(gammas[0])
    T1_all = float(gammas[-1])
    dT     = T1_all - T0_all

    # Define non-overlapping sub-windows
    w_size = dT / N_WINDOWS
    windows = [(T0_all + i*w_size, T0_all + (i+1)*w_size) for i in range(N_WINDOWS)]

    print(f"\n  Sub-windows (N_WINDOWS={N_WINDOWS}):")
    for i, (T0, T1) in enumerate(windows):
        mask = (gammas >= T0) & (gammas <= T1)
        print(f"    Win {i}: T=[{T0:.1f},{T1:.1f}]  N={mask.sum()}")

    print(f"\n  Survival criterion: z > {Z_SURVIVE} in >= {SURVIVE_NULLS}/3 nulls "
          f"AND in >= {SURVIVE_WINDOWS}/3 windows")
    print(f"  Null methods: {list(NULL_METHODS.keys())}")
    print(f"  Window types: hann, tukey")

    # ── Full grid (all k) for context + targets ───────────────────────────────
    all_results = {}  # k -> list of probe results across windows and window types

    print(f"\n  {'k':>4}  {'u':>8}  ", end="")
    for wi in range(N_WINDOWS):
        print(f"  Win{wi}(hann) z[PR/BP/GUE]", end="")
    print(f"  {'VERDICT':>10}")
    print(f"  {'-'*90}")

    target_set = set(TARGET_K)

    for k in ALL_K:
        u = k * LOG2
        k_results = []

        for wi, (T0, T1) in enumerate(windows):
            r_hann = probe_adversarial(gammas, k, T0, T1, wi, mode="hann")
            k_results.append(r_hann)

        # Count windows where null criterion is met (>= SURVIVE_NULLS)
        wins_survived = sum(1 for r in k_results if r["survives_null_criterion"])
        final_survives = wins_survived >= SURVIVE_WINDOWS

        all_results[k] = {
            "probes":         k_results,
            "wins_survived":  wins_survived,
            "final_survives": final_survives,
            "is_target":      k in target_set,
        }

        # Print row
        flag = "**TARGET**" if k in target_set else ""
        verdict = "SURVIVES" if final_survives else "dies"
        row_z = ""
        for r in k_results:
            zs = "/".join(
                f"{r[nm]['z']:+.1f}" for nm in NULL_METHODS
            )
            row_z += f"  [{zs}]"
        print(f"  {k:>4}  {u:>8.3f}{row_z}  {verdict:<10} {flag}")

    # ── Target summary ────────────────────────────────────────────────────────
    print(f"\n" + "="*70)
    print(f"  ADVERSARIAL VERDICT — Targets k = {TARGET_K}")
    print(f"="*70)

    target_verdicts = {}
    for k in TARGET_K:
        res = all_results[k]
        v = "REAL STRUCTURE" if res["final_survives"] else "ARTEFACT (does not survive)"
        target_verdicts[k] = v
        print(f"\n  k={k}  u={k*LOG2:.4f}  wins_survived={res['wins_survived']}/3")
        print(f"    --> {v}")
        for wi, r in enumerate(res["probes"]):
            print(f"    Win {wi}: T=[{r['T0']:.1f},{r['T1']:.1f}]  "
                  f"null_survive={r['nulls_survived']}/3  "
                  f"z_PR={r['phase_random']['z']:.2f}  "
                  f"z_BP={r['block_perm']['z']:.2f}  "
                  f"z_GUE={r['gue_surrogate']['z']:.2f}")

    print(f"\n  INTERPRETATION:")
    survivors = [k for k in TARGET_K if all_results[k]["final_survives"]]
    if survivors:
        print(f"  k = {survivors}: SURVIVE adversarial audit.")
        print(f"  These are NOT artefacts of window/nul choice.")
        print(f"  Candidate for 'real structure in u=k*log(2) spectrum.'")
        print(f"  Still NOT a claim of Mersenne primalidad — separate hypothesis needed.")
    else:
        print(f"  No targets survive. All flagged peaks were artefacts.")
        print(f"  Layer C anomaly is closed: window/null artefact confirmed.")

    return {
        "target_verdicts": target_verdicts,
        "all_k": {str(k): {"wins_survived": v["wins_survived"],
                            "final_survives": v["final_survives"],
                            "is_target": v["is_target"]}
                  for k, v in all_results.items()},
        "survivors": survivors,
    }


if __name__ == "__main__":
    print("="*70)
    print("  GAHENAX LAYER C ADVERSARIAL AUDIT")
    print(f"  Targets: k = {TARGET_K}  (flagged in Phase-1 Layer C)")
    print(f"  Survival criterion: z>{Z_SURVIVE} in >={SURVIVE_NULLS}/3 nulls, >={SURVIVE_WINDOWS}/3 windows")
    print("="*70)

    gammas = load_gammas()

    if len(gammas) < 200:
        print("[ERROR] Insufficient zeros. Run phase3_aggregator.py first.")
        sys.exit(1)

    verdict = run_adversarial_audit(gammas)

    out_path = os.path.join(PROJECT, "results", "riemann", "layer_c_adversarial_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"experiment": "layer_c_adversarial_phase3",
                   "params": {"TARGET_K": TARGET_K, "Z_SURVIVE": Z_SURVIVE,
                               "SURVIVE_NULLS": SURVIVE_NULLS,
                               "SURVIVE_WINDOWS": SURVIVE_WINDOWS,
                               "B_NULL": B_NULL},
                   "verdict": verdict}, f, indent=2)
    print(f"\n  Report saved: {out_path}")
