#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
collider_resonance_analyzer.py
==============================
Analyzes collider events to see if prime resonance survives Breit-Wigner smearing.
"""

import json
import numpy as np
import math
import os
import time
from typing import List, Dict, Any

def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def prime_powers_up_to(xmax: float) -> np.ndarray:
    def sieve(n):
        is_p = np.ones(n + 1, dtype=bool)
        is_p[:2] = False
        for p in range(2, int(n**0.5) + 1):
            if is_p[p]: is_p[p*p:n+1:p] = False
        return np.where(is_p)[0]
    
    primes = sieve(int(xmax))
    powers = []
    for p in primes:
        v = p
        while v <= xmax:
            powers.append(v)
            if v > xmax/p: break
            v *= p
    return np.sort(np.array(powers))

def reconstruct_psi_fluctuations(x: np.ndarray, gammas: np.ndarray) -> np.ndarray:
    """Simplified Psi reconstruction for sampled gammas (spectrum)."""
    logx = np.log(x)
    sqrtx = np.sqrt(x)
    psi_fluct = np.zeros_like(x)
    
    # Process in blocks to save memory/speed
    B = 512
    for i in range(0, len(gammas), B):
        g = gammas[i:i+B]
        # phase = g * log(x)
        phases = np.outer(g, logx)
        # term = sqrt(x) * cos(phase) / |1/2 + ig| 
        # approx |1/2 + ig| ~ g for large g
        denoms = np.sqrt(0.25 + g**2)
        terms = (sqrtx[None, :] * np.cos(phases)) / denoms[:, None]
        psi_fluct -= 2.0 * np.sum(terms, axis=0)
        
    # Standardize to see the jumps
    return (psi_fluct - np.mean(psi_fluct)) / np.std(psi_fluct)

def compute_resonance_score(x: np.ndarray, psi_f: np.ndarray, primes: np.ndarray, band: float = 0.2) -> float:
    d_psi = np.abs(np.diff(psi_f))
    x_mid = 0.5 * (x[1:] + x[:-1])
    
    # Top 200 spikes
    idx = np.argpartition(d_psi, -200)[-200:]
    spike_x = x_mid[idx]
    
    hits = 0
    for sx in spike_x:
        if np.any(np.abs(primes - sx) <= band):
            hits += 1
    return hits / len(spike_x)

def main():
    events_path = "collider_events_highres.json"
    if not os.path.exists(events_path):
        print("Error: collider_events.json logic not found.")
        return

    print("[ANALYZER] Loading collider events...")
    data = read_json(events_path)
    masses = np.array(data["masses"])
    
    # Filter out very high masses to focus on the dense region
    masses = masses[masses < 500]
    
    x = np.linspace(2.0, 150.0, 15000)
    primes = prime_powers_up_to(150.0)
    
    print(f"[ANALYZER] Reconstructing Prime Resonance from {len(masses)} events...")
    start_t = time.time()
    psi_f = reconstruct_psi_fluctuations(x, masses)
    
    score = compute_resonance_score(x, psi_f, primes)
    duration = time.time() - start_t
    
    print(f"\n[RESULTS] Analysis Complete in {duration:.2f}s")
    print(f"  - Events used: {len(masses)}")
    print(f"  - Prime Hit Rate (Coherence): {score*100:.1f}%")
    
    # Check against a random control of the same size
    print("[ANALYZER] Running Poisson control check...")
    random_masses = np.random.uniform(14, 500, size=len(masses))
    psi_rand = reconstruct_psi_fluctuations(x, random_masses)
    rand_score = compute_resonance_score(x, psi_rand, primes)
    
    print(f"  - Control Hit Rate (Chance): {rand_score*100:.1f}%")
    
    verdict = "STRONG" if score > 2 * rand_score else "WEAK"
    print(f"\n[VERDICT] Riemann Coherence is {verdict} in this collider sample.")

    report = {
        "score": score,
        "control_score": rand_score,
        "improvement_factor": score / max(1e-6, rand_score),
        "verdict": verdict,
        "n_events": len(masses)
    }
    with open("collider_analysis_report.json", "w") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    main()
