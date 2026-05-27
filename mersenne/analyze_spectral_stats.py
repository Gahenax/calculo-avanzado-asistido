import json
import math
import argparse
import sys
import numpy as np
from pathlib import Path

def riemann_smooth_N(t):
    if t <= 0: return 0
    return (t / (2 * math.pi)) * math.log(t / (2 * math.pi)) - (t / (2 * math.pi)) + 7/8

def load_zeros(path: Path):
    zeros = []
    keys = ["refined_T", "T", "t", "zero", "t_est"]
    
    content = ""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-16")
        
    for line in content.splitlines():
        if not line.strip(): continue
        try:
            obj = json.loads(line)
            val = None
            for k in keys:
                if k in obj:
                    val = float(obj[k])
                    break
            if val: zeros.append(val)
        except: continue
            
    zeros = sorted(set(zeros))
    return np.array(zeros)

def unfold_spectrum(zeros):
    """Map T_n to x_n using smooth counting function."""
    return np.array([riemann_smooth_N(t) for t in zeros])

def compute_r_stats(unfolded):
    gaps = np.diff(unfolded)
    # r_n = min(s_n, s_{n+1}) / max(s_n, s_{n+1})
    r_vals = []
    for i in range(len(gaps)-1):
        s_n = gaps[i]
        s_next = gaps[i+1]
        r = min(s_n, s_next) / max(s_n, s_next)
        r_vals.append(r)
    return np.array(r_vals)

def compute_number_variance(unfolded, L_max=20, steps=20):
    # Sigma^2(L): Variance of number of levels in interval L
    
    L_values = np.linspace(1, L_max, steps)
    sigma2_values = []
    
    x_min = unfolded[0]
    x_max = unfolded[-1]
    range_span = x_max - x_min
    
    for L in L_values:
        if L >= range_span: 
            sigma2_values.append(0)
            continue
            
        num_samples = 1000
        centers = np.linspace(x_min + L/2, x_max - L/2, num_samples)
        
        counts = []
        for c in centers:
            idx_start = np.searchsorted(unfolded, c - L/2)
            idx_end = np.searchsorted(unfolded, c + L/2)
            count = idx_end - idx_start
            counts.append(count)
            
        sigma2 = np.var(counts)
        sigma2_values.append(sigma2)
        
    return L_values, np.array(sigma2_values)

def analyze_dataset(file_path, min_t=None, max_t=None):
    zeros = load_zeros(Path(file_path))
    
    if min_t is not None:
        zeros = zeros[zeros >= min_t]
    if max_t is not None:
        zeros = zeros[zeros <= max_t]
        
    if len(zeros) < 50:
        print(f"Not enough zeros for robust spectral stats (Found {len(zeros)}).")
        return

    print(f"--- GAHENAX SPECTRAL AUDIT ---")
    print(f"Dataset: {file_path}")
    print(f"Zeros Loaded: {len(zeros)}")
    print(f"Range T: [{zeros[0]:.2f}, {zeros[-1]:.2f}]")
    
    # 1. Unfold
    unfolded = unfold_spectrum(zeros)
    gaps = np.diff(unfolded)
    mean_gap = gaps.mean()
    
    # Re-normalize exactly to 1.0 for stats
    unfolded = unfolded / mean_gap
    
    # 2. r-statistics
    r_vals = compute_r_stats(unfolded)
    mean_r = r_vals.mean()
    gue_r = 0.5996
    
    print(f"\n[1] L-STATISTIC (LOCAL ORDER)")
    print(f"Observed <r>: {mean_r:.5f}")
    print(f"GUE Expected: {gue_r:.5f}")
    print(f"Deviation:    {abs(mean_r - gue_r):.5f}")
    
    # 3. Number Variance (The Chaos Measurement)
    print(f"\n[2] NUMBER VARIANCE Sigma^2(L) (GLOBAL CHAOS)")
    L_vals, sigma2 = compute_number_variance(unfolded, L_max=10, steps=10)
    
    print(f"{'L':<8} | {'Sigma^2 (Obs)':<12} | {'Sigma^2 (GUE)':<12} | {'Ratio':<8}")
    print("-" * 50)
    for l, sig in zip(L_vals, sigma2):
        if l < 0.1: continue
        gue_sig = (1 / math.pi**2) * (math.log(2 * math.pi * l) + 1 + 0.5772)
        ratio = sig / gue_sig if gue_sig > 0 else 0
        print(f"{l:<8.1f} | {sig:<12.4f} | {gue_sig:<12.4f} | {ratio:<8.2%}")

    # 4. Final Verdict
    print(f"\n--- VERDICT ---")
    if ratio < 0.5:
        print("STATUS: [GREEN] SUPER-RIGID (Anomalous Order)")
    elif ratio < 1.1:
        print("STATUS: [GREEN] GUE-COMPATIBLE (Standard Quantum Chaos)")
    else:
        print("STATUS: [RED] DRIFT-WARN (High Noise/Chaos)")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--min_t", type=float, default=None)
    ap.add_argument("--max_t", type=float, default=None)
    args = ap.parse_args()
    
    analyze_dataset(args.file, min_t=args.min_t, max_t=args.max_t)
