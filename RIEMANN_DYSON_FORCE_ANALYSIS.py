#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import numpy as np
import os
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

def normalize_t(t: np.ndarray) -> np.ndarray:
    """
    Normaliza por densidad local aproximada:
      t -> t * log(t / (2*pi)) / (2*pi)
    Nota: Usamos la versión de Riemann-von Mangoldt más precisa:
    N(T) ~ (T/2pi) log(T/2pi) - T/2pi + 7/8
    Pero para espaciado local, el factor de escala es log(T/2pi)/(2pi).
    """
    t = np.asarray(t, dtype=float)
    if np.any(t <= 2 * math.pi):
        # Fallback for very low T
        return t
    return t * np.log(t / (2.0 * math.pi)) / (2.0 * math.pi)

def local_force(t: np.ndarray, K: int = 20, use_normalized: bool = True) -> np.ndarray:
    """
    Fuerza truncada local:
      F_i = sum_{m=1..K} (1/(x_i-x_{i-m}) + 1/(x_i-x_{i+m}))
    donde x = normalize_t(t) si use_normalized else t.
    """
    t = np.asarray(t, dtype=float)
    if t.ndim != 1 or t.size < (2 * K + 1):
        # Try a smaller K if N is small
        K = max(1, (t.size - 1) // 2)
        print(f"Adjusting K to {K} due to small N={t.size}")

    x = normalize_t(t) if use_normalized else t
    x = np.sort(x)

    N = x.size
    F = np.full(N, np.nan, dtype=float)

    for i in range(K, N - K):
        xi = x[i]
        s = 0.0
        for m in range(1, K + 1):
            s += 1.0 / (xi - x[i - m])
            s += 1.0 / (xi - x[i + m])
        F[i] = s

    return F

def robust_stats(arr: np.ndarray) -> dict:
    a = arr[np.isfinite(arr)]
    if a.size == 0:
        return {"n": 0}
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med)))
    return {
        "n": int(a.size),
        "mean": float(np.mean(a)),
        "std": float(np.std(a, ddof=1)) if a.size > 1 else 0.0,
        "median": med,
        "mad": mad,
        "p05": float(np.percentile(a, 5)),
        "p95": float(np.percentile(a, 95)),
    }

def main():
    # Load zeros from JSONL
    roots = []
    
    # Prioritize drill results as they are more complete
    paths = ["drill_final_coverage.jsonl", "zeros_final_mining.jsonl"]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("accepted"):
                            roots.append(float(data["root"]))
                    except:
                        continue
    
    if not roots:
        print("No zeros found in JSONL files.")
        return

    # Use unique roots and sort them
    t = np.unique(roots)
    print(f"Loaded {len(t)} unique zeros for analysis.")

    K = 20  # vecinos a cada lado
    if len(t) < 2*K + 1:
        K = (len(t) - 1) // 2
        
    F = local_force(t, K=K, use_normalized=True)

    stats = robust_stats(F)
    print("\n--- DYSON FORCE ANALYSIS ---")
    for k, v in stats.items():
        print(f"{k:8s}: {v}")

    # Diagnóstico de drift: ajuste lineal en la región interior
    idx = np.arange(F.size)
    mask = np.isfinite(F)
    x_coords = idx[mask].astype(float)
    y_coords = F[mask]
    
    if y_coords.size >= 10:
        A = np.vstack([x_coords, np.ones_like(x_coords)]).T
        slope, intercept = np.linalg.lstsq(A, y_coords, rcond=None)[0]
        print(f"DRIFT_FIT: slope={slope:.6e} intercept={intercept:.6e}")
        
    # Save results to a report file
    report = {
        "stats": stats,
        "drift": {"slope": float(slope), "intercept": float(intercept)} if y_coords.size >= 10 else None,
        "n_zeros": len(t),
        "K": K
    }
    with open("results_dyson_force.json", "w") as f:
        json.dump(report, f, indent=2)

    if HAS_MATPLOTLIB:
        # Note: plt.show() might not work in headless environments, 
        # so we save the figure instead.
        plt.figure(figsize=(11, 4))
        plt.plot(idx, F, marker=".", linestyle="none", color="cyan", alpha=0.6)
        plt.axhline(0.0, color="red", linestyle="--")
        plt.title(f"Riemann Zeros: Truncated Dyson Force (K={K}) on Normalized Levels")
        plt.xlabel("Zero Index (i)")
        plt.ylabel("F_i (Truncated Interaction)")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig("riemann_dyson_force.png")
        print("\nPlot saved as riemann_dyson_force.png")
    else:
        print("\nMatplotlib not found. Skipping plot generation.")

if __name__ == "__main__":
    main()
