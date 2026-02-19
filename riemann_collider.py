#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
riemann_collider.py
===================
OUROBOROS LAB — Riemann Resonance Collider Simulator

This script simulates a particle collider (toy model) where the "resonances"
(particle masses) are determined by the imaginary parts of Riemann zeta zeros.

It generates invariant mass distributions combining:
1) A Power-Law Background (continuum).
2) Riemann Resonances (Breit-Wigner peaks centered at zeta zeros).

Auditable Physics:
- If the reconstruction (SFF/Chebyshev) shows prime structure, the 'physical'
  events are correlated through the zeta zeros.
"""

import json
import numpy as np
import math
import os
import argparse
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ----------------------------
# Riemann & Sampling Logic
# ----------------------------

def load_gammas_json(path: str) -> np.ndarray:
    if not os.path.exists(path):
        print(f"Warning: {path} not found. Using empty gammas.")
        return np.array([], dtype=float)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        g = np.array(data, dtype=float)
    elif isinstance(data, dict) and "zeros" in data:
        g = np.array(data["zeros"], dtype=float)
    else:
        g = np.array([], dtype=float)

    g = g[np.isfinite(g)]
    g = np.abs(g)
    g = np.unique(g)
    g.sort()
    return g

def sample_breit_wigner(rng: np.random.Generator, m0: float, gamma: float) -> float:
    """Samples from the relativistic Breit-Wigner distribution."""
    # Standard Cauchy/BW sampling
    while True:
        u = rng.uniform(0.0, 1.0)
        m = m0 + 0.5 * gamma * math.tan(math.pi * (u - 0.5))
        # Keep mass positive and within reasonable bounds
        if m > 1.0:
            return float(m)

def _normalize_weights(w: np.ndarray) -> np.ndarray:
    w = np.clip(w, 0.0, np.inf)
    s = float(np.sum(w))
    if not np.isfinite(s) or s <= 0:
        return np.ones_like(w) / float(len(w))
    return w / s

def make_gamma_weights(gammas: np.ndarray, mode: str = "flat") -> np.ndarray:
    """
    Weights for choosing which resonances are populated.
    - flat: all equal
    - inv: ~ 1/gamma (favors lower zeros)
    - inv2: ~ 1/gamma^2 (more aggressive)
    - exp: ~ exp(-a*gamma)
    """
    g = gammas.astype(float)
    eps = 1e-12
    if mode == "flat":
        w = np.ones_like(g)
    elif mode == "inv":
        w = 1.0 / (g + eps)
    elif mode == "inv2":
        w = 1.0 / ((g + eps) ** 2)
    elif mode == "exp":
        a = 0.002
        w = np.exp(-a * g)
    else:
        raise ValueError(f"Unknown weight mode: {mode}")
    return _normalize_weights(w)

def sample_riemann_resonance(
    rng: np.random.Generator,
    gammas: np.ndarray,
    width: float,
    weights: np.ndarray = None,
) -> float:
    """Selects a gamma as m0 and samples a BW around it."""
    if len(gammas) == 0:
        return float(rng.uniform(10.0, 1000.0)) # Fallback
    if weights is None:
        idx = int(rng.integers(0, len(gammas)))
    else:
        idx = int(rng.choice(len(gammas), p=weights))
    m0 = float(gammas[idx])
    return sample_breit_wigner(rng, m0, float(width))

def sample_powerlaw_m(rng: np.random.Generator, m_min: float, m_max: float, n: float) -> float:
    """Samples from a power-law background P(m) ~ m^-n."""
    u = rng.uniform(0.0, 1.0)
    # Inverse transform sampling for x^-n
    # Integral of x^-n is x^(1-n)/(1-n)
    if abs(n - 1.0) < 1e-9:
        return m_min * math.exp(u * math.log(m_max / m_min))
    
    exp_term = 1.0 - n
    m = (u * (m_max**exp_term - m_min**exp_term) + m_min**exp_term)**(1.0 / exp_term)
    return float(m)

# ----------------------------
# Simulator Engine
# ----------------------------

@dataclass
class ColliderConfig:
    n_events: int = 100000
    signal_fraction: float = 0.1
    width: float = 0.5
    bkg_m_min: float = 10.0
    bkg_m_max: float = 2000.0
    bkg_power_n: float = 2.0
    zeros_json: str = "ALL_ZEROS_FINAL.json"
    riemann_weight_mode: str = "inv"
    seed: int = 42
    
    # Runtime fields
    riemann_gammas: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))
    riemann_weights: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))

def generate_collider_event(rng: np.random.Generator, cfg: ColliderConfig) -> Tuple[float, str]:
    """Generates a single event (invariant mass)."""
    kind = "signal" if rng.uniform(0, 1) < cfg.signal_fraction else "background"
    
    if kind == "signal":
        m = sample_riemann_resonance(
            rng=rng,
            gammas=cfg.riemann_gammas,
            width=cfg.width,
            weights=cfg.riemann_weights,
        )
    else:
        m = sample_powerlaw_m(rng, cfg.bkg_m_min, cfg.bkg_m_max, cfg.bkg_power_n)
        
    return float(m), kind

def main():
    parser = argparse.ArgumentParser(description="Riemann Resonance Collider Simulator")
    parser.add_argument("--n_events", type=int, default=100000)
    parser.add_argument("--signal_fraction", type=float, default=0.1)
    parser.add_argument("--width", type=float, default=0.5)
    parser.add_argument("--zeros_json", type=str, default="ALL_ZEROS_FINAL.json")
    parser.add_argument("--out", type=str, default="collider_events.json")
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()

    # Initialize Config
    cfg = ColliderConfig(
        n_events=args.n_events,
        signal_fraction=args.signal_fraction,
        width=args.width,
        zeros_json=args.zeros_json
    )
    
    # Load Riemann Data
    cfg.riemann_gammas = load_gammas_json(cfg.zeros_json)
    if len(cfg.riemann_gammas) > 0:
        cfg.riemann_weights = make_gamma_weights(cfg.riemann_gammas, mode=cfg.riemann_weight_mode)
        print(f"Loaded {len(cfg.riemann_gammas)} resonances from {cfg.zeros_json}")
    else:
        print("Warning: Starting collider with no resonances (only background).")

    rng = np.random.default_rng(cfg.seed)
    
    print(f"Simulating {cfg.n_events} events...")
    start_t = time.time()
    
    masses = []
    kinds = []
    
    for _ in range(cfg.n_events):
        m, kind = generate_collider_event(rng, cfg)
        masses.append(m)
        kinds.append(kind)
        
    duration = time.time() - start_t
    print(f"Done in {duration:.2f}s ({cfg.n_events/duration:.0f} events/s)")
    
    # Save Results
    events_out = []
    for i in range(min(10000, len(masses))):
        events_out.append({
            "m": masses[i],
            "kind": 1 if kinds[i] == "signal" else 0
        })

    output = {
        "config": {
            "n_events": cfg.n_events,
            "signal_fraction": cfg.signal_fraction,
            "width": cfg.width,
            "zeros_source": cfg.zeros_json
        },
        "statistics": {
            "signal_count": kinds.count("signal"),
            "background_count": kinds.count("background")
        },
        "events": events_out
    }
    
    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Results (first 10k events) saved to {args.out}")

    # Plotting
    if args.plot and HAS_MATPLOTLIB:
        plt.figure(figsize=(12, 7))
        m_arr = np.array(masses)
        plt.hist(m_arr, bins=200, range=(0, 500), histtype='step', label='Total', color='black')
        
        sig_m = np.array([m for m, k in zip(masses, kinds) if k == "signal"])
        if len(sig_m) > 0:
            plt.hist(sig_m, bins=200, range=(0, 500), histtype='stepfilled', alpha=0.3, label='Riemann Signal', color='blue')
            
        plt.yscale('log')
        plt.title(f"Riemann Collider Invariant Mass Spectrum (N={cfg.n_events}, w={cfg.width})")
        plt.xlabel("Invariant Mass [GeV-ish / Gamma]")
        plt.ylabel("Events / Bin")
        plt.legend()
        plt.grid(True, which='both', alpha=0.2)
        plt.savefig("riemann_collider_spectrum.png")
        print("Plot saved to riemann_collider_spectrum.png")

if __name__ == "__main__":
    main()
