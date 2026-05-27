
import json
import math
import numpy as np
import scipy.stats as stats
from pathlib import Path

def riemann_smooth_N(t):
    if t <= 0: return 0
    return (t / (2 * math.pi)) * math.log(t / (2 * math.pi)) - (t / (2 * math.pi)) + 7/8

def load_zeros(path: Path):
    zeros = []
    keys = ["refined_T", "T", "t", "zero", "t_est"]
    if not path.exists():
        return np.array([])
    content = path.read_text(encoding="utf-8", errors="ignore")
    for line in content.splitlines():
        if not line.strip(): continue
        try:
            obj = json.loads(line)
            # Handle nested payload if present
            data = obj.get("payload", obj) if isinstance(obj, dict) else obj
            val = None
            for k in keys:
                if k in data:
                    val = float(data[k])
                    break
            if val: zeros.append(val)
        except: continue
    res = np.array(sorted(set(zeros)))
    # print(f"DEBUG: Loaded {len(res)} unique zeros from {path.name}")
    return res

def analyze_patterns(file_path):
    zeros = load_zeros(Path(file_path))
    if len(zeros) < 100:
        print(f"Error: Dataset too small ({len(zeros)} zeros). Need >= 100.")
        return

    print(f"=== GAHENAX PATTERN MINER v1.0 ===")
    print(f"Source: {file_path}")
    print(f"Sample Size: {len(zeros)} zeros")
    print(f"Range: [{zeros[0]:.2f}, {zeros[-1]:.2f}]")

    # 1. Unfolding
    unfolded = np.array([riemann_smooth_N(t) for t in zeros])
    gaps = np.diff(unfolded)
    
    print(f"DEBUG: Computing Spacing Dynamics...")
    # Normalize gaps to mean 1.0
    mean_gap = np.mean(gaps)
    unfolded_norm = (unfolded - unfolded[0]) / mean_gap
    
    # 2. Resonant Residues (Fluctuations around the mean)
    # delta_n = (Expected Index) - (Actual Index)
    indices = np.arange(len(unfolded_norm))
    residues = unfolded_norm - indices
    
    # 3. Frequency Analysis (Fourier of residues)
    # Looking for 'Spectral Heartbeat' or periodic drift
    print(f"DEBUG: Performing FFT...")
    fft_vals = np.abs(np.fft.rfft(residues - np.mean(residues)))
    limit = len(fft_vals)
    freqs = np.fft.rfftfreq(len(residues))
    
    # Find dominant peak (excluding DC)
    peak_idx = np.argmax(fft_vals[1:]) + 1
    peak_freq = freqs[peak_idx]
    peak_power = fft_vals[peak_idx]
    
    # 4. Spacing Correlation (ACF of gaps)
    # GUE zeros have negative correlation at lag 1 (anti-clustering)
    acf_lag1 = np.corrcoef(gaps[:-1], gaps[1:])[0, 1]

    print(f"\n[1] SPACING DYNAMICS")
    print(f"Mean Gap (unfolded): {mean_gap:.5f}")
    print(f"Lag-1 ACF:           {acf_lag1:.4f} (Expected GUE: ~ -0.25)")
    
    if acf_lag1 < -0.35:
        print("VERDICT: Super-Rigid Spacing detected (Possible Hyperuniformity).")
    elif acf_lag1 > -0.15:
        print("VERDICT: Softened Spacing (Possible Spectrum Decay/Noise).")
    else:
        print("VERDICT: Standard GUE Rigidity.")

    print(f"\n[2] SPECTRAL RESONANCE (FFT of residues)")
    print(f"Peak Frequency:      {peak_freq:.5f} [cycles/zero]")
    print(f"Peak Power:          {peak_power:.2f}")
    
    # Entropy of residues (measure of chaos in the drift)
    hist, _ = np.histogram(residues, bins=min(20, len(residues)//10), density=True)
    residue_entropy = stats.entropy(hist + 1e-9)
    print(f"Residue Entropy:     {residue_entropy:.4f}")

    print(f"\n[3] NUMBER VARIANCE Sigma^2(L=1.0)")
    print(f"DEBUG: Computing Number Variance...")
    # Sigma^2(1) for GUE is approx 0.44
    L = 1.0
    samples = 500
    offsets = np.linspace(unfolded_norm[10], unfolded_norm[-10] - L, samples)
    #counts = [np.sum((unfolded_norm >= o) & (unfolded_norm < o+L)) for o in offsets]
    # Faster version
    counts = []
    for o in offsets:
        counts.append(np.searchsorted(unfolded_norm, o + L) - np.searchsorted(unfolded_norm, o))
    s2_1 = np.var(counts)
    print(f"Observed Sigma^2(1): {s2_1:.4f} (GUE: ~0.44)")

    print(f"\n--- PATTERN SUMMARY ---")
    if peak_power > 15.0: # Arbitrary threshold for demo
        print(f"STATUS: [FOUND] Strong Spectral Echo at f={peak_freq:.3f}")
    else:
        print("STATUS: [CLEAN] No significant periodic patterns in residues.")

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else r'c:\Users\USUARIO\OneDrive\Desktop\Tesis\results\riemann\data_5000_6319.jsonl'
    analyze_patterns(target)
