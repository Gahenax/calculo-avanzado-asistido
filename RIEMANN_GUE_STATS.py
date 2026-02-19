import json
import math
import numpy as np
import os

def n_riemann_von_mangoldt(t):
    """Approximate number of zeros up to t."""
    if t <= 0: return 0
    return (t / (2 * math.pi)) * (math.log(t / (2 * math.pi)) - 1) + 7/8

def calculate_stats(source_file):
    zeros = []
    with open(source_file, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("status") == "CONFIRMED":
                    t = data.get("t_root") or data.get("refined_T")
                    if t:
                        zeros.append(float(t))
            except:
                continue
    
    zeros = sorted(list(set(zeros)))
    if len(zeros) < 3:
        return {"error": "Not enough zeros found"}

    # Unfolding
    unfolded = [n_riemann_von_mangoldt(t) for t in zeros]
    spacings = np.diff(unfolded)
    
    # r-ratios: r_n = min(s_n, s_{n-1}) / max(s_n, s_{n-1})
    r_ratios = []
    for i in range(1, len(spacings)):
        s1 = spacings[i-1]
        s2 = spacings[i]
        if s1 > 0 and s2 > 0:
            r_ratios.append(min(s1, s2) / max(s1, s2))
    
    r_mean = float(np.mean(r_ratios))
    
    # KS distance vs GUE (approx)
    # GUE spacing distribution p(s) approx (32/pi^2) * s^2 * exp(-4s^2/pi)
    # CDF(s) = erf(2s/sqrt(pi)) - (4s/pi) * exp(-4s^2/pi)
    def gue_cdf(s):
        return math.erf(s * 2 / math.sqrt(math.pi)) - (4 * s / math.pi) * math.exp(-4 * s**2 / math.pi)

    # Normalize spacings to mean 1
    s_norm = spacings / np.mean(spacings)
    s_sorted = np.sort(s_norm)
    n = len(s_sorted)
    
    ks_stat = 0
    for i, s in enumerate(s_sorted):
        empirical = (i + 1) / n
        theoretical = gue_cdf(s)
        ks_stat = max(ks_stat, abs(empirical - theoretical))

    return {
        "n_zeros": len(zeros),
        "r_mean": r_mean,
        "ks_gue": ks_stat,
        "t_min": min(zeros),
        "t_max": max(zeros),
        "spacings": s_norm.tolist(),
        "block": "found_zeros"
    }

def main():
    source = "riemann_mining_results.jsonl"
    report_path = "results/riemann_stats.json"
    
    print(f"Analyzing {source}...")
    stats = calculate_stats(source)
    
    os.makedirs("results", exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"Stats saved to {report_path}")
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()
