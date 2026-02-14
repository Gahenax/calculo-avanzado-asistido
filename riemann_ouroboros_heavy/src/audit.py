#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py — Post-iteration audit for OUROBOROS HEAVY.
Reads merged CSV, computes per-(type,intensity) summaries,
robustness checks, outlier scores, and writes reports.
"""
import csv
import json
import os
import numpy as np
from collections import defaultdict
from typing import Dict, Any, List


def load_merged_csv(path: str) -> List[Dict[str, Any]]:
    """Load all rows from merged CSV."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k in ["seed"]:
                if k in row and row[k]:
                    try: row[k] = int(row[k])
                    except: pass
            for k in ["r_mean", "r_std", "r_entropy", "ks_gue", "ks_poi",
                       "ks_margin", "reducer_ks", "reducer_entropy_delta"]:
                if k in row and row[k]:
                    try: row[k] = float(row[k])
                    except: pass
            rows.append(row)
    return rows


def compute_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summary by (type, intensity): vote_rate, mean ks_margin, etc."""
    groups = defaultdict(list)
    for r in rows:
        key = (r.get("type", "?"), r.get("intensity", "?"))
        groups[key].append(r)

    summary = {}
    for (btype, intensity), group in groups.items():
        n = len(group)
        votes_gue = sum(1 for r in group if r.get("vote") == "GUE")
        margins = [r.get("ks_margin", 0) for r in group
                    if isinstance(r.get("ks_margin"), (int, float))]
        r_means = [r.get("r_mean", 0) for r in group
                    if isinstance(r.get("r_mean"), (int, float))]

        summary[f"{btype}|{intensity}"] = {
            "n_blocks": n,
            "vote_rate_gue": round(votes_gue / max(n, 1), 4),
            "mean_ks_margin": round(float(np.mean(margins)), 6) if margins else 0.0,
            "std_ks_margin": round(float(np.std(margins)), 6) if margins else 0.0,
            "mean_r": round(float(np.mean(r_means)), 6) if r_means else 0.0,
        }

    return summary


def compute_robustness(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    For ZETA blocks: check if vote is consistent across intensities.
    Robust if GUE vote rate > 0.6 in at least 2/3 intensities.
    """
    zeta_rows = [r for r in rows if r.get("type") == "zeta"]
    if not zeta_rows:
        return {"zeta_available": False}

    by_intensity = defaultdict(list)
    for r in zeta_rows:
        by_intensity[r.get("intensity", "?")].append(r)

    intensity_votes = {}
    passing = 0
    total_intensities = len(by_intensity)

    for intensity, group in by_intensity.items():
        n = len(group)
        gue = sum(1 for r in group if r.get("vote") == "GUE")
        rate = gue / max(n, 1)
        intensity_votes[intensity] = {
            "n": n, "gue_votes": gue, "vote_rate": round(rate, 4)
        }
        if rate > 0.6:
            passing += 1

    robust = passing >= max(1, total_intensities * 2 // 3)

    return {
        "zeta_available": True,
        "intensities": intensity_votes,
        "passing_intensities": passing,
        "total_intensities": total_intensities,
        "robust": robust,
    }


def compute_outliers(rows: List[Dict[str, Any]],
                     topk: int = 40) -> List[Dict[str, Any]]:
    """Top outliers by |ks_margin|."""
    valid = []
    for r in rows:
        margin = r.get("ks_margin")
        if isinstance(margin, (int, float)) and np.isfinite(margin):
            valid.append({
                "block_id": r.get("block_id", "?"),
                "type": r.get("type", "?"),
                "intensity": r.get("intensity", "?"),
                "r_mean": r.get("r_mean", 0),
                "ks_gue": r.get("ks_gue", 0),
                "ks_poi": r.get("ks_poi", 0),
                "ks_margin": round(float(margin), 6),
                "vote": r.get("vote", "?"),
            })

    valid.sort(key=lambda x: -abs(x["ks_margin"]))
    return valid[:topk]


def run_audit(merged_csv: str, report_json: str,
              outliers_csv: str, topk: int = 40) -> Dict[str, Any]:
    """Full audit pipeline."""
    rows = load_merged_csv(merged_csv)
    summary = compute_summary(rows)
    robustness = compute_robustness(rows)
    outliers = compute_outliers(rows, topk)

    report = {
        "total_rows": len(rows),
        "summary_by_type_intensity": summary,
        "robustness": robustness,
        "top_outliers_count": len(outliers),
    }

    # Write report
    os.makedirs(os.path.dirname(report_json), exist_ok=True)
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    # Write outliers CSV
    if outliers:
        os.makedirs(os.path.dirname(outliers_csv), exist_ok=True)
        keys = list(outliers[0].keys())
        with open(outliers_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(outliers)

    return report
