import json
import numpy as np
from scipy.stats import wasserstein_distance
import os

def load_jsonl(path):
    data = []
    with open(path, 'r') as f:
        for line in f:
            data.append(json.loads(line))
    return data

def main():
    riemann_stats_path = "results/riemann_stats.json"
    cronos_grid_path = "results/cronos_grid_stats.jsonl"
    output_path = "results/alignment_report.json"
    
    if not os.path.exists(riemann_stats_path) or not os.path.exists(cronos_grid_path):
        print("Required files missing.")
        return

    with open(riemann_stats_path, 'r') as f:
        riemann = json.load(f)
    
    cronos_grid = load_jsonl(cronos_grid_path)
    
    r_spacings = np.array(riemann["spacings"])
    
    alignments = []
    for point in cronos_grid:
        c_spacings = np.array(point["spacings"])
        dist = wasserstein_distance(r_spacings, c_spacings)
        alignments.append({
            "L": point["L"],
            "W": point["W"],
            "r_mean": point["r_mean"],
            "wasserstein": float(dist)
        })
    
    # Sort by wasserstein distance
    alignments.sort(key=lambda x: x["wasserstein"])
    
    best = alignments[0]
    worst = alignments[-1]
    
    report = {
        "best_match": best,
        "worst_match": worst,
        "all_alignments": alignments,
        "lowW_closer_than_highW": best["W"] < 5.0 # Check hypothesis H3
    }
    
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"Alignment report saved to {output_path}")
    print(f"Best Match: L={best['L']} W={best['W']} dist={best['wasserstein']:.4f}")

if __name__ == "__main__":
    main()
