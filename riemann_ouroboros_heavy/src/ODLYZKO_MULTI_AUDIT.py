#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODLYZKO_MULTI_AUDIT.py
=======================
Run gap-ratio KS audit on any spacings .npy file.

Usage:
    python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros3.npy --label zeros3
    python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros4.npy --label zeros4
    python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros5.npy --label zeros5
"""
from __future__ import annotations
import argparse, json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from controls import gue_spacings, poisson_spacings, build_disjoint_blocks_from_spacings
from metrics import gap_ratios, hist_entropy
from entropy_reducer import entropy_reduce_1d
from io_utils import StreamingCSVWriter
from audit import run_audit

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BLOCK_LEN = 200
N_REF = 80
GUE_MAT_N = 180
BULK_LO, BULK_HI = 0.2, 0.8
CTRL_BLOCKS = 50

INTENSITIES = [
    {"name": "raw",    "median_k": 0, "ema_alpha": 0,   "winsor_w": 0,  "p_lo": 0,   "p_hi": 100, "ks_max": 1.0},
    {"name": "soft",   "median_k": 5, "ema_alpha": 0.04,"winsor_w": 21, "p_lo": 2.5, "p_hi": 97.5,"ks_max": 0.18},
    {"name": "mid",    "median_k": 7, "ema_alpha": 0.06,"winsor_w": 25, "p_lo": 2.5, "p_hi": 97.5,"ks_max": 0.16},
    {"name": "strong", "median_k": 9, "ema_alpha": 0.08,"winsor_w": 31, "p_lo": 3.0, "p_hi": 97.0,"ks_max": 0.14},
]

CSV_COLS = ["type","block_id","seed","intensity","r_mean","r_std","r_entropy",
            "ks_gue","ks_poi","ks_margin","vote","reducer_ks","reducer_mode"]


def process_block(block, intensity, r_gue_ref, r_poi_ref):
    from scipy import stats as _st
    spacings = np.asarray(block["spacings"], dtype=np.float64)
    r = gap_ratios(spacings)
    if len(r) < 10:
        return {"type": block["type"], "block_id": block["block_id"], "vote": "INSUFFICIENT"}

    reducer_ks, reducer_mode = 0.0, "none"
    if intensity["name"] != "raw" and intensity["median_k"] > 0:
        r_reduced, rinfo = entropy_reduce_1d(r, median_k=intensity["median_k"],
            ema_alpha=intensity["ema_alpha"], winsor_w=intensity["winsor_w"],
            p_lo=intensity["p_lo"], p_hi=intensity["p_hi"], ks_max=intensity["ks_max"])
        reducer_ks, reducer_mode = rinfo["ks"], rinfo["mode"]
    else:
        r_reduced = r

    r_mean = float(np.mean(r_reduced))
    r_std = float(np.std(r_reduced))
    r_ent = hist_entropy(r_reduced)
    ks_g = float(_st.ks_2samp(r_reduced, r_gue_ref).statistic)
    ks_p = float(_st.ks_2samp(r_reduced, r_poi_ref).statistic)
    margin = ks_p - ks_g
    vote = "GUE" if ks_g < ks_p else "POISSON"

    return {"type": block["type"], "block_id": block["block_id"],
            "seed": block.get("seed", 0), "intensity": intensity["name"],
            "r_mean": round(r_mean, 6), "r_std": round(r_std, 6),
            "r_entropy": round(r_ent, 6), "ks_gue": round(ks_g, 6),
            "ks_poi": round(ks_p, 6), "ks_margin": round(margin, 6),
            "vote": vote, "reducer_ks": round(reducer_ks, 6),
            "reducer_mode": reducer_mode}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spacings", required=True, help="Path to spacings .npy")
    ap.add_argument("--label", required=True, help="Label (e.g. zeros3)")
    args = ap.parse_args()

    out_dir = os.path.join("data", f"audit_{args.label}")
    os.makedirs(out_dir, exist_ok=True)
    merged = os.path.join(out_dir, f"merged_{args.label}.csv")
    report = os.path.join(out_dir, f"audit_report_{args.label}.json")
    outliers = os.path.join(out_dir, f"outliers_{args.label}.csv")

    print(f"\n{'='*60}", flush=True)
    print(f"  MULTI AUDIT: {args.label}", flush=True)
    print(f"  Spacings: {args.spacings}", flush=True)
    print(f"{'='*60}\n", flush=True)
    t0 = time.time()

    spacings = np.load(args.spacings)
    n_avail = len(spacings) // BLOCK_LEN
    print(f"  Spacings: {len(spacings):,}, blocks available: {n_avail}", flush=True)

    # References
    print(f"  Building references...", flush=True)
    r_gue_ref = np.concatenate([gap_ratios(gue_spacings(BLOCK_LEN, seed=70000+i,
        mat_n=GUE_MAT_N, bulk_lo=BULK_LO, bulk_hi=BULK_HI)) for i in range(N_REF)])
    r_poi_ref = np.concatenate([gap_ratios(poisson_spacings(BLOCK_LEN, seed=80000+i))
        for i in range(N_REF)])
    print(f"  GUE ref: {len(r_gue_ref)} (mean={np.mean(r_gue_ref):.4f})", flush=True)
    print(f"  POI ref: {len(r_poi_ref)} (mean={np.mean(r_poi_ref):.4f})", flush=True)

    # Blocks
    zeta_blocks = build_disjoint_blocks_from_spacings(spacings, n_avail, BLOCK_LEN, 42, "zeta")
    gue_blocks = build_disjoint_blocks_from_spacings(np.array([]), CTRL_BLOCKS, BLOCK_LEN, 80000, "gue")
    poi_blocks = build_disjoint_blocks_from_spacings(np.array([]), CTRL_BLOCKS, BLOCK_LEN, 90000, "poisson")
    all_blocks = zeta_blocks + gue_blocks + poi_blocks
    print(f"  Blocks: {len(zeta_blocks)} zeta + {len(gue_blocks)} gue + {len(poi_blocks)} poi", flush=True)

    # Process
    writer = StreamingCSVWriter(merged, flush_every=20)
    writer.write_header_once(CSV_COLS)
    for bi, block in enumerate(all_blocks):
        for intensity in INTENSITIES:
            row = process_block(block, intensity, r_gue_ref, r_poi_ref)
            writer.write_rows([row])
        if (bi+1) % 25 == 0 or bi == len(all_blocks)-1:
            print(f"    {bi+1}/{len(all_blocks)} blocks", flush=True)
    writer.flush()
    writer.close()

    # Audit
    rpt = run_audit(merged, report, outliers, topk=20)

    # Summary
    print(f"\n{'='*60}", flush=True)
    print(f"  RESULTS: {args.label}", flush=True)
    print(f"{'='*60}", flush=True)
    for key in sorted(rpt.get("summary_by_type_intensity", {}).keys()):
        s = rpt["summary_by_type_intensity"][key]
        print(f"  {key:<25} n={s['n_blocks']:>4}  "
              f"vote_GUE={s['vote_rate_gue']:>6.1%}  "
              f"margin={s['mean_ks_margin']:>+8.4f}", flush=True)

    rob = rpt.get("robustness", {})
    if rob.get("zeta_available"):
        for intname, iv in rob.get("intensities", {}).items():
            st = "PASS" if iv["vote_rate"] > 0.6 else "FAIL"
            print(f"  Robustness {intname}: {iv['vote_rate']:.0%} [{st}]", flush=True)

        verdict = "ZETA_FAVORS_GUE" if rob.get("robust") else "INCONCLUSIVE"
        print(f"\n  VERDICT: {verdict}", flush=True)

    print(f"  Time: {time.time()-t0:.1f}s", flush=True)
    print(f"{'='*60}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
