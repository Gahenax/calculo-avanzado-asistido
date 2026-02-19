#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
collider_to_spectrum.py
======================
Bridge: collider_events.json -> estimated resonance centers (gammas_hat)

Assumes collider_events.json is a list[dict] or dict with "events": list[dict]
with at least a mass field: "mll" or "mass" or "m".

Outputs:
- spectrum_hat.json with fields:
  { "gammas_hat": [...], "weights_hat": [...], "meta": {...} }

Then you feed gammas_hat into PRIME_OSCILLATOR_PSI / prime_resonance_driver.
"""

import argparse
import json
import math
import os
from typing import Any, Dict, List, Tuple

import numpy as np


def load_events(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "events" in data:
        evs = data["events"]
    elif isinstance(data, list):
        evs = data
    else:
        raise ValueError("Unsupported collider_events.json format")

    if not isinstance(evs, list):
        raise ValueError("events is not a list")
    return [e for e in evs if isinstance(e, dict)]


def get_mass_array(events: List[Dict[str, Any]]) -> np.ndarray:
    keys = ["mll", "mass", "m", "m_inv"]
    masses = []
    for e in events:
        v = None
        for k in keys:
            if k in e:
                v = e[k]
                break
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isfinite(fv) and fv > 0:
            masses.append(fv)
    return np.array(masses, dtype=float)


def filter_signal(events: List[Dict[str, Any]], require_accepted: bool = True) -> List[Dict[str, Any]]:
    out = []
    for e in events:
        if require_accepted and ("accepted" in e) and float(e["accepted"]) < 0.5:
            continue
        if "kind" in e:
            # en tu chasis anterior: kind=1 signal, 0 bkg
            if float(e["kind"]) < 0.5:
                continue
        out.append(e)
    return out


def kde_gaussian_1d(x: np.ndarray, grid: np.ndarray, bw: float) -> np.ndarray:
    """
    Simple Gaussian KDE: sum exp(-(g-x)^2/(2*bw^2))
    Returns unnormalized density (fine for peak finding).
    """
    bw = float(bw)
    if bw <= 0:
        raise ValueError("bw must be > 0")
    inv2 = 1.0 / (2.0 * bw * bw)
    dens = np.zeros_like(grid, dtype=float)
    # block for memory
    B = 2048
    for i in range(0, len(x), B):
        xb = x[i:i+B]
        # (len(grid), len(block)) broadcasting
        d2 = (grid[:, None] - xb[None, :]) ** 2
        dens += np.sum(np.exp(-d2 * inv2), axis=1)
    return dens


def find_peaks(y: np.ndarray, min_prominence: float, min_distance: int) -> List[int]:
    """
    Basic peak finder: local maxima with prominence threshold and distance in indices.
    Prominence is approximated as y[i] - max(min(y[left]), min(y[right])) in a window.
    """
    n = len(y)
    candidates = []
    for i in range(1, n - 1):
        if y[i] > y[i - 1] and y[i] > y[i + 1]:
            candidates.append(i)

    # compute crude prominence
    peaks = []
    for i in candidates:
        left_min = np.min(y[max(0, i - min_distance):i]) if i - min_distance >= 0 else np.min(y[:i])
        right_min = np.min(y[i + 1:i + 1 + min_distance]) if i + 1 + min_distance <= n else np.min(y[i + 1:])
        base = max(left_min, right_min)
        prom = y[i] - base
        if prom >= min_prominence:
            peaks.append((i, y[i], prom))

    # sort by height, enforce min_distance
    peaks.sort(key=lambda t: t[1], reverse=True)
    chosen = []
    taken = np.zeros(n, dtype=bool)
    for i, height, prom in peaks:
        lo = max(0, i - min_distance)
        hi = min(n, i + min_distance + 1)
        if taken[lo:hi].any():
            continue
        chosen.append(i)
        taken[lo:hi] = True

    chosen.sort()
    return chosen


def estimate_spectrum_from_masses(
    masses: np.ndarray,
    bw: float,
    grid_step: float,
    min_prominence: float,
    min_distance: float,
    max_peaks: int,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    mmin = float(np.min(masses))
    mmax = float(np.max(masses))

    grid = np.arange(mmin, mmax + grid_step, grid_step, dtype=float)
    dens = kde_gaussian_1d(masses, grid, bw=bw)

    min_dist_idx = max(1, int(round(min_distance / grid_step)))
    peak_idx = find_peaks(dens, min_prominence=min_prominence, min_distance=min_dist_idx)

    # cap peaks
    if max_peaks > 0 and len(peak_idx) > max_peaks:
        # keep the tallest ones
        heights = dens[peak_idx]
        order = np.argsort(-heights)[:max_peaks]
        peak_idx = sorted([peak_idx[i] for i in order])

    gammas_hat = grid[peak_idx]

    # weights: use density height at peak as proxy
    weights_hat = dens[peak_idx]
    if len(weights_hat) > 0:
        weights_hat = weights_hat / np.sum(weights_hat)

    meta = {
        "mmin": mmin,
        "mmax": mmax,
        "bw": float(bw),
        "grid_step": float(grid_step),
        "min_prominence": float(min_prominence),
        "min_distance": float(min_distance),
        "num_events_used": int(len(masses)),
        "num_peaks": int(len(gammas_hat)),
    }
    return gammas_hat, weights_hat, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events_json", required=True)
    ap.add_argument("--out_json", default="spectrum_hat.json")
    ap.add_argument("--require_accepted", action="store_true")
    ap.add_argument("--bw", type=float, default=0.10, help="KDE bandwidth (should match width/smear scale)")
    ap.add_argument("--grid_step", type=float, default=0.02)
    ap.add_argument("--min_prominence", type=float, default=5.0, help="Depends on event count; tune once.")
    ap.add_argument("--min_distance", type=float, default=0.10, help="In mass units (GeV-like).")
    ap.add_argument("--max_peaks", type=int, default=2000)
    args = ap.parse_args()

    events = load_events(args.events_json)
    events_sel = filter_signal(events, require_accepted=args.require_accepted)
    masses = get_mass_array(events_sel)

    if len(masses) < 100:
        raise ValueError("Too few masses after filtering; check keys or filters.")

    gammas_hat, weights_hat, meta = estimate_spectrum_from_masses(
        masses=masses,
        bw=args.bw,
        grid_step=args.grid_step,
        min_prominence=args.min_prominence,
        min_distance=args.min_distance,
        max_peaks=args.max_peaks,
    )

    out = {
        "gammas_hat": gammas_hat.tolist(),
        "weights_hat": weights_hat.tolist(),
        "meta": meta,
    }
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    print(f"[*] Wrote: {args.out_json}")
    print(f"[*] Peaks found: {meta['num_peaks']}")
    print(f"[*] Mass range: [{meta['mmin']:.3f}, {meta['mmax']:.3f}]  events_used={meta['num_events_used']}")


if __name__ == "__main__":
    main()
