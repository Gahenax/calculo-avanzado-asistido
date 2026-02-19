#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
energy_recovery_test.py
======================
OUROBOROS LAB — Energy Recovery Test (Spectrum Hat -> ψ Reconstruction)
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import math
import os
import pathlib
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# ----------------------------
# IO helpers
# ----------------------------

def ensure_dir(p: str) -> None:
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)

def now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# ----------------------------
# Number theory: primes + prime powers
# ----------------------------

def sieve_primes(n: int) -> List[int]:
    if n < 2:
        return []
    is_prime = np.ones(n + 1, dtype=bool)
    is_prime[:2] = False
    lim = int(math.isqrt(n))
    for p in range(2, lim + 1):
        if is_prime[p]:
            is_prime[p*p:n+1:p] = False
    return [i for i in range(2, n + 1) if is_prime[i]]

def prime_powers_up_to(xmax: float) -> np.ndarray:
    xmax_i = int(math.floor(xmax))
    primes = sieve_primes(xmax_i)
    vals: List[int] = []
    for p in primes:
        v = p
        while v <= xmax:
            vals.append(v)
            if v > xmax / p:
                break
            v *= p
    vals = sorted(set(vals))
    return np.array(vals, dtype=float)

def build_near_mask(x_mid: np.ndarray, pp_vals: np.ndarray, band: float) -> np.ndarray:
    mask = np.zeros_like(x_mid, dtype=bool)
    b = float(band)
    for v in pp_vals:
        mask |= np.abs(x_mid - v) <= b
    return mask


# ----------------------------
# Signal processing
# ----------------------------

def moving_average(y: np.ndarray, k: int) -> np.ndarray:
    k = int(k)
    if k <= 1:
        return y
    kernel = np.ones(k, dtype=float) / float(k)
    return np.convolve(y, kernel, mode="same")


# ----------------------------
# Explicit formula reconstruction ψ(x)
# ----------------------------

def psi_from_gammas_weighted(
    x: np.ndarray,
    gammas: np.ndarray,
    weights: np.ndarray,
    window_alpha: float = 0.0,
    phase_scramble: bool = False,
    scramble_seed: int = 0,
    block_size: int = 256,
) -> np.ndarray:
    x = x.astype(float)
    logx = np.log(x)
    sqrtx = np.sqrt(x)

    gammas = gammas.astype(float)
    weights = weights.astype(float)

    # normalize weights (safe)
    weights = np.clip(weights, 0.0, np.inf)
    sw = float(np.sum(weights))
    if not np.isfinite(sw) or sw <= 0:
        weights = np.ones_like(weights) / float(len(weights))
    else:
        weights = weights / sw

    rho_real = 0.5
    psi = x.copy()
    psi -= math.log(2.0 * math.pi)

    if len(gammas) == 0:
        return psi

    rng = np.random.default_rng(int(scramble_seed)) if phase_scramble else None
    B = int(block_size)

    for i in range(0, len(gammas), B):
        g = gammas[i:i+B]
        w_block = weights[i:i+B]

        denom = rho_real + 1j * g

        if window_alpha and window_alpha > 0.0:
            win = np.exp(-float(window_alpha) * g)
        else:
            win = 1.0

        phase = np.outer(g, logx)
        if phase_scramble and rng is not None:
            phi = rng.uniform(0.0, 2.0 * math.pi, size=len(g))
            phase = phase + phi[:, None]

        # Use numpys vectorization for speed
        e = np.exp(1j * phase)
        term = (sqrtx[None, :] * e) / denom[:, None]

        # apply weights + window
        psi -= 2.0 * np.real(((w_block * win)[:, None] * term).sum(axis=0))

    return psi


# ----------------------------
# Metrics
# ----------------------------

def compute_metrics(
    x: np.ndarray,
    psi: np.ndarray,
    pp_vals: np.ndarray,
    band: float,
    topK: int,
) -> Dict[str, float]:
    dpsi = np.diff(psi)
    x_mid = 0.5 * (x[1:] + x[:-1])

    mask_near = build_near_mask(x_mid, pp_vals, band=float(band))
    energy_near = float(np.mean(dpsi[mask_near] ** 2)) if mask_near.any() else float("nan")
    energy_far = float(np.mean(dpsi[~mask_near] ** 2)) if (~mask_near).any() else float("nan")

    ratio = float("nan")
    if np.isfinite(energy_near) and np.isfinite(energy_far) and energy_far > 0:
        ratio = float(energy_near / energy_far)

    topK = int(topK)
    if topK <= 0:
        hit_rate = float("nan")
    else:
        k_val = min(topK, len(dpsi))
        idx = np.argpartition(np.abs(dpsi), -k_val)[-k_val:]
        spike_x = x_mid[idx]
        hits = 0
        for sx in spike_x:
            if np.any(np.abs(pp_vals - sx) <= float(band)):
                hits += 1
        hit_rate = float(hits / len(spike_x)) if len(spike_x) else float("nan")

    return {
        "energy_near": energy_near,
        "energy_far": energy_far,
        "ratio_near_far": ratio,
        "hit_rate_topK": hit_rate,
    }


# ----------------------------
# Weight modes
# ----------------------------

def weights_mode(gammas: np.ndarray, weights_hat: Optional[np.ndarray], mode: str) -> np.ndarray:
    g = gammas.astype(float)
    eps = 1e-12

    if mode == "flat":
        w = np.ones_like(g)
    elif mode == "kde":
        if weights_hat is None or len(weights_hat) != len(g):
            raise ValueError("weights_hat missing or length mismatch for mode=kde")
        w = np.array(weights_hat, dtype=float)
    elif mode == "inv":
        w = 1.0 / (g + eps)
    elif mode == "kde_inv":
        if weights_hat is None or len(weights_hat) != len(g):
            raise ValueError("weights_hat missing or length mismatch for mode=kde_inv")
        w = np.array(weights_hat, dtype=float) / (g + eps)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    w = np.clip(w, 0.0, np.inf)
    return w


# ----------------------------
# Plotting
# ----------------------------

def plot_dpsi(
    x: np.ndarray,
    psi: np.ndarray,
    pp_vals: np.ndarray,
    out_path: str,
    title: str,
    xmax: float,
) -> None:
    if not HAS_MATPLOTLIB: return
    dpsi = np.diff(psi)
    x_mid = 0.5 * (x[1:] + x[:-1])

    plt.figure(figsize=(12, 6))
    plt.plot(x_mid, dpsi, linewidth=1)
    plt.title(title)
    plt.xlabel("x")
    plt.ylabel("Δψ")
    plt.grid(True, alpha=0.3)

    for v in pp_vals:
        if v <= xmax:
            plt.axvline(float(v), linestyle="--", alpha=0.08)

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


# ----------------------------
# Main
# ----------------------------

@dataclasses.dataclass(frozen=True)
class ConfigRun:
    spectrum_json: str
    out_dir: str
    xmax: float
    num_points: int
    band: float
    window_alpha: float
    smooth_k: int
    topK: int
    seed: int
    modes: Tuple[str, ...]


def load_spectrum_hat(path: str) -> Tuple[np.ndarray, Optional[np.ndarray], Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("spectrum_json must be a dict with gammas_hat")

    if "gammas_hat" in data:
        gammas = np.array(data["gammas_hat"], dtype=float)
    elif "zeros" in data:
        gammas = np.array(data["zeros"], dtype=float)
    else:
        raise ValueError("No gammas_hat or zeros found in spectrum_json")

    gammas = gammas[np.isfinite(gammas)]
    gammas = np.abs(gammas)
    gammas = np.unique(gammas)
    gammas.sort()

    w_hat = None
    # We trust weights_hat is aligned with peaks if produced by the bridge
    if "weights_hat" in data and isinstance(data["weights_hat"], list):
        w_hat = np.array(data["weights_hat"], dtype=float)
        if len(w_hat) != len(gammas):
            w_hat = None

    meta = data.get("meta", {})
    return gammas, w_hat, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spectrum_json", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--xmax", type=float, default=200.0)
    ap.add_argument("--num_points", type=int, default=20000)
    ap.add_argument("--band", type=float, default=0.2)
    ap.add_argument("--window_alpha", type=float, default=0.0)
    ap.add_argument("--smooth_k", type=int, default=5)
    ap.add_argument("--topK", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--modes", nargs="+", default=["flat", "kde", "inv", "kde_inv"])
    args = ap.parse_args()

    ensure_dir(args.out_dir)

    gammas, weights_hat, meta = load_spectrum_hat(args.spectrum_json)
    if len(gammas) == 0:
        raise ValueError("Empty gammas")

    # x grid
    x = np.linspace(2.0, args.xmax, args.num_points)
    pp_vals = prime_powers_up_to(args.xmax)

    results = []
    for mode in args.modes:
        w = weights_mode(gammas, weights_hat, mode=mode)

        psi = psi_from_gammas_weighted(
            x=x,
            gammas=gammas,
            weights=w,
            window_alpha=args.window_alpha,
            phase_scramble=False,
            scramble_seed=args.seed,
            block_size=256,
        )
        if args.smooth_k > 1:
            psi = moving_average(psi, args.smooth_k)

        metrics = compute_metrics(
            x=x,
            psi=psi,
            pp_vals=pp_vals,
            band=args.band,
            topK=args.topK,
        )

        run = {
            "mode": mode,
            "Ngamma": int(len(gammas)),
            "metrics": metrics,
        }
        results.append(run)

        # artifacts
        out_png = os.path.join(args.out_dir, f"dpsi_{mode}.png")
        if HAS_MATPLOTLIB:
            plot_dpsi(x, psi, pp_vals, out_png, f"Δψ(x) — mode={mode}", args.xmax)

        print(f"[*] mode={mode:8}  ratio={metrics['ratio_near_far']:.4f}  hit={metrics['hit_rate_topK']:.4f}")

    summary = {
        "experiment": "energy_recovery_test",
        "timestamp_utc": now_iso(),
        "Ngamma": int(len(gammas)),
        "results": results,
    }
    write_json(os.path.join(args.out_dir, "summary_energy_recovery.json"), summary)
    print(f"[*] Wrote summary: {os.path.join(args.out_dir, 'summary_energy_recovery.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
