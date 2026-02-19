import numpy as np
from scipy.stats import wasserstein_distance
from typing import List, Dict, Any

def get_r_ratios(spacings: np.ndarray) -> np.ndarray:
    """Calculates r_n = min(s_n, s_{n-1}) / max(s_n, s_{n-1})."""
    r_ratios = []
    for i in range(1, len(spacings)):
        s1, s2 = spacings[i-1], spacings[i]
        if s1 > 1e-12 and s2 > 1e-12:
            r_ratios.append(min(s1, s2) / max(s1, s2))
    return np.array(r_ratios)

def analyze_spectrum(levels: List[float], unfolded: bool = False) -> Dict[str, Any]:
    """Performs full spectral analysis on a list of energy levels or zeros."""
    lvls = np.sort(levels)
    if not unfolded:
        # Standard unfolding assumes mean spacing 1 locally
        # For small blocks, linear unfolding is often sufficient if densities are stable
        spacings = np.diff(lvls)
    else:
        spacings = np.diff(lvls)
    
    s_norm = spacings / np.mean(spacings)
    r_ratios = get_r_ratios(spacings)
    
    return {
        "n": len(lvls),
        "r_mean": float(np.mean(r_ratios)) if len(r_ratios) > 0 else 0.0,
        "r_std": float(np.std(r_ratios)) if len(r_ratios) > 0 else 0.0,
        "spacings_norm": s_norm.tolist()
    }

def compare_dists(s1: List[float], s2: List[float]) -> float:
    """Returns the Wasserstein distance between two normalized spacing distributions."""
    return float(wasserstein_distance(s1, s2))
