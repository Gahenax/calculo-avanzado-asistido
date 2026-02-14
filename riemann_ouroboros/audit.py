#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py
========
Audit engine for OUROBOROS pipeline.
Reads merged_flow_traces.csv, computes per-block final features,
generates summary by type, outlier scores, and exports reports.
"""
import csv
import json
import os
import numpy as np
from typing import Dict, Any, List, Optional
from collections import defaultdict


def read_merged_csv(filepath: str) -> List[Dict[str, Any]]:
    """Read all rows from merged CSV."""
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
            for k in ["step", "run_id", "seed"]:
                if k in row and row[k]:
                    try:
                        row[k] = int(row[k])
                    except (ValueError, TypeError):
                        pass
            for k in ["time", "radius_mean", "radius_var", "sphericity",
                       "laplacian_energy", "mean_flow_norm", "max_flow_norm",
                       "reducer_ks", "reducer_entropy_before", "reducer_entropy_after"]:
                if k in row and row[k]:
                    try:
                        row[k] = float(row[k])
                    except (ValueError, TypeError):
                        pass
            rows.append(row)
    return rows


def extract_final_states(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group by (type, block_id) and take the last row per block."""
    groups = defaultdict(list)
    for r in rows:
        key = (r.get("type", "?"), r.get("block_id", "?"))
        groups[key].append(r)

    finals = []
    for (btype, bid), group in groups.items():
        # Sort by step to get the last one
        group.sort(key=lambda x: x.get("step", 0))
        last = dict(group[-1])
        last["_type"] = btype
        last["_block_id"] = bid
        finals.append(last)

    return finals


# Feature vector for each block's final state
FEATURE_KEYS = [
    "radius_var", "sphericity", "laplacian_energy",
    "mean_flow_norm", "reducer_ks",
]


def extract_features(final: Dict[str, Any]) -> np.ndarray:
    """Extract numeric feature vector from final state dict."""
    feats = []
    for k in FEATURE_KEYS:
        v = final.get(k, 0.0)
        if isinstance(v, (int, float)) and np.isfinite(v):
            feats.append(float(v))
        else:
            feats.append(0.0)
    return np.array(feats, dtype=np.float64)


def compute_summary_by_type(finals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate statistics by block type."""
    by_type = defaultdict(list)
    for f in finals:
        by_type[f["_type"]].append(f)

    summary = {}
    for btype, blocks in by_type.items():
        n = len(blocks)
        statuses = [b.get("status", "?") for b in blocks]
        converged = sum(1 for s in statuses if s == "converged")
        stalled = sum(1 for s in statuses if s == "stalled")

        feats = np.array([extract_features(b) for b in blocks])
        means = feats.mean(axis=0) if n > 0 else np.zeros(len(FEATURE_KEYS))
        stds = feats.std(axis=0) if n > 1 else np.zeros(len(FEATURE_KEYS))

        summary[btype] = {
            "n_blocks": n,
            "pct_converged": round(100 * converged / max(n, 1), 1),
            "pct_stalled": round(100 * stalled / max(n, 1), 1),
            "feature_means": {k: round(float(means[i]), 8) for i, k in enumerate(FEATURE_KEYS)},
            "feature_stds": {k: round(float(stds[i]), 8) for i, k in enumerate(FEATURE_KEYS)},
        }

    return summary


def compute_outlier_scores(
    finals: List[Dict[str, Any]],
    topk: int = 30,
) -> List[Dict[str, Any]]:
    """
    Compute outlier scores.
    For each block, score = dist(block, gue_centroid) - dist(block, poisson_centroid).
    Negative = closer to GUE. Positive = closer to Poisson.
    """
    by_type = defaultdict(list)
    for f in finals:
        by_type[f["_type"]].append(f)

    # Compute centroids
    centroids = {}
    for btype in ["gue", "poisson"]:
        blocks = by_type.get(btype, [])
        if blocks:
            feats = np.array([extract_features(b) for b in blocks])
            centroids[btype] = feats.mean(axis=0)
        else:
            centroids[btype] = np.zeros(len(FEATURE_KEYS))

    # Standardize using combined stats
    all_feats = np.array([extract_features(f) for f in finals])
    if len(all_feats) < 2:
        return []
    global_mean = all_feats.mean(axis=0)
    global_std = all_feats.std(axis=0)
    global_std = np.where(global_std < 1e-12, 1.0, global_std)

    gue_c = (centroids["gue"] - global_mean) / global_std
    poi_c = (centroids["poisson"] - global_mean) / global_std

    outliers = []
    for f in finals:
        feat = (extract_features(f) - global_mean) / global_std
        d_gue = float(np.linalg.norm(feat - gue_c))
        d_poi = float(np.linalg.norm(feat - poi_c))
        score = d_gue - d_poi  # negative = closer to GUE

        outliers.append({
            "block_id": f["_block_id"],
            "type": f["_type"],
            "status": f.get("status", "?"),
            "d_gue": round(d_gue, 6),
            "d_poi": round(d_poi, 6),
            "outlier_score": round(score, 6),
            "radius_var": f.get("radius_var", 0),
            "sphericity": f.get("sphericity", 0),
            "laplacian_energy": f.get("laplacian_energy", 0),
        })

    # Sort by absolute outlier score (most extreme first)
    outliers.sort(key=lambda x: -abs(x["outlier_score"]))
    return outliers[:topk]


def run_audit(
    merged_csv_path: str,
    output_dir: str,
    topk: int = 30,
) -> Dict[str, Any]:
    """
    Full audit pipeline.
    Returns the audit report dict and writes:
      - audit_report.json
      - outliers.csv
    """
    rows = read_merged_csv(merged_csv_path)
    finals = extract_final_states(rows)

    summary = compute_summary_by_type(finals)
    outliers = compute_outlier_scores(finals, topk=topk)

    report = {
        "total_rows": len(rows),
        "total_blocks": len(finals),
        "summary_by_type": summary,
        "top_outliers": outliers[:10],  # top 10 in report
    }

    # Write report
    report_path = os.path.join(output_dir, "audit_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    # Write outliers CSV
    outlier_path = os.path.join(output_dir, "outliers.csv")
    if outliers:
        keys = list(outliers[0].keys())
        with open(outlier_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(outliers)

    return report
