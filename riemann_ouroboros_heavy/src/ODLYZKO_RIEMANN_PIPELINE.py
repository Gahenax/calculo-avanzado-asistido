#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ODLYZKO_RIEMANN_PIPELINE.py
============================
Download Odlyzko's precomputed Riemann zeta zeros and validate.

Source: https://www.dtc.umn.edu/~odlyzko/zeta_tables/
- zeros1: first 100,000 zeros (1.8 MB)
- zeros6: first 2,001,052 zeros (35 MB)

Pipeline:
  1. Download plain text table
  2. Parse each line as a float (imaginary part of zero)
  3. Validate: monotonicity, gaps, density via N(T)
  4. Save as .npy + .txt + metadata JSON

Usage:
  python ODLYZKO_RIEMANN_PIPELINE.py                     # 100k zeros
  python ODLYZKO_RIEMANN_PIPELINE.py --table zeros6      # 2M zeros
  python ODLYZKO_RIEMANN_PIPELINE.py --table zeros1 --strict
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ============================================================================
# CONFIG
# ============================================================================

ODLYZKO_TABLES = {
    "zeros1": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros1",
        "description": "First 100,000 zeros, accurate to 3e-9",
        "expected_count": 100000,
        "size_mb": 1.8,
    },
    "zeros2": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros2",
        "description": "First 100 zeros, 1000+ decimal places",
        "expected_count": 100,
        "size_mb": 0.1,
    },
    "zeros3": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros3",
        "description": "Zeros 10^12+1 through 10^12+10^4",
        "expected_count": 10000,
        "size_mb": 0.5,
    },
    "zeros4": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros4",
        "description": "Zeros 10^21+1 through 10^21+10^4",
        "expected_count": 10000,
        "size_mb": 0.5,
    },
    "zeros5": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros5",
        "description": "Zeros 10^22+1 through 10^22+10^4",
        "expected_count": 10000,
        "size_mb": 0.5,
    },
    "zeros6": {
        "url": "https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros6",
        "description": "First 2,001,052 zeros, accurate to 4e-9",
        "expected_count": 2001052,
        "size_mb": 35.0,
    },
}

OUTPUT_DIR = Path("data")


# ============================================================================
# DOWNLOAD
# ============================================================================

def download_table(url: str, retries: int = 3, timeout: int = 120) -> str:
    """Download with exponential backoff."""
    req = Request(url, headers={
        "User-Agent": "AcademicResearchBot/1.0 (Zeta zeros analysis)",
    })
    last_err = None
    for i in range(retries):
        try:
            print(f"  Downloading {url} (attempt {i+1})...", flush=True)
            with urlopen(req, timeout=timeout) as r:
                data = r.read()
                print(f"  Downloaded {len(data)/1024/1024:.1f} MB", flush=True)
                return data.decode("utf-8", errors="replace")
        except (URLError, HTTPError, TimeoutError) as e:
            last_err = e
            wait = 2 ** i
            print(f"  Retry in {wait}s: {e}", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Download failed after {retries} attempts: {last_err}")


# ============================================================================
# PARSE
# ============================================================================

def parse_zeros(text: str) -> np.ndarray:
    """Parse one float per line from Odlyzko table format."""
    values = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            v = float(line)
            if v > 0:
                values.append(v)
        except ValueError:
            continue
    return np.array(values, dtype=np.float64)


# ============================================================================
# VALIDATION
# ============================================================================

def N_von_mangoldt(T: float) -> float:
    """N(T) approx = (T/2pi)*log(T/2pi) - T/2pi + 7/8."""
    if T <= 0:
        return 0.0
    a = T / (2.0 * math.pi)
    return a * math.log(a) - a + 0.875


def validate(zeros: np.ndarray, strict: bool = False) -> dict:
    """Full validation: monotonicity, gaps, density."""
    n = len(zeros)
    info = {"n_zeros": n, "valid": True, "issues": []}

    if n < 10:
        info["valid"] = False
        info["issues"].append("Too few zeros")
        return info

    # Sort check (Odlyzko tables should be sorted)
    if not np.all(np.diff(zeros) > 0):
        info["issues"].append("NOT monotonic - sorting")
        zeros.sort()

    # Gaps
    gaps = np.diff(zeros)
    info["min_gap"] = float(np.min(gaps))
    info["max_gap"] = float(np.max(gaps))
    info["mean_gap"] = float(np.mean(gaps))
    info["t_min"] = float(zeros[0])
    info["t_max"] = float(zeros[-1])

    if info["max_gap"] > 50.0:
        msg = f"Large gap: {info['max_gap']:.4f}"
        info["issues"].append(msg)
        if strict:
            info["valid"] = False

    # Density check
    T0, T1 = float(zeros[0]), float(zeros[-1])
    expected = N_von_mangoldt(T1) - N_von_mangoldt(T0)
    observed = float(n - 1)
    ratio = observed / expected if expected > 0 else 0.0
    info["density_ratio"] = round(ratio, 6)
    info["expected_count_in_range"] = round(expected, 1)

    if ratio < 0.5 or ratio > 1.8:
        msg = f"Density anomaly: observed/expected = {ratio:.3f}"
        info["issues"].append(msg)
        if strict:
            info["valid"] = False

    return info


# ============================================================================
# UNFOLDING
# ============================================================================

def compute_unfolded_spacings(zeros: np.ndarray) -> np.ndarray:
    """Riemann-von Mangoldt unfolding -> normalized spacings."""
    t = np.sort(zeros)
    two_pi = 2.0 * np.pi
    t_over_2pi = t / two_pi
    N = t_over_2pi * np.log(t_over_2pi) - t_over_2pi + 7.0 / 8.0
    spacings = np.diff(N)
    mean_s = np.mean(spacings)
    if mean_s > 0:
        spacings = spacings / mean_s
    return spacings


# ============================================================================
# MAIN
# ============================================================================

def main():
    ap = argparse.ArgumentParser(description="Odlyzko Zeta Zeros Pipeline")
    ap.add_argument("--table", type=str, default="zeros1",
                    choices=list(ODLYZKO_TABLES.keys()),
                    help="Which Odlyzko table to download")
    ap.add_argument("--strict", action="store_true",
                    help="Abort on validation anomalies")
    ap.add_argument("--max_zeros", type=int, default=0,
                    help="Limit number of zeros (0 = all)")
    args = ap.parse_args()

    table = ODLYZKO_TABLES[args.table]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", flush=True)
    print(f"ODLYZKO RIEMANN PIPELINE", flush=True)
    print(f"  Table: {args.table}", flush=True)
    print(f"  Description: {table['description']}", flush=True)
    print(f"  Expected: ~{table['expected_count']:,} zeros ({table['size_mb']} MB)", flush=True)
    print(f"{'='*60}\n", flush=True)

    t0 = time.time()

    # Download
    print("[PHASE 1] Downloading...", flush=True)
    raw_path = OUTPUT_DIR / f"{args.table}_raw.txt"
    if raw_path.exists():
        print(f"  [CACHE HIT] {raw_path}", flush=True)
        text = raw_path.read_text(encoding="utf-8")
    else:
        text = download_table(table["url"])
        raw_path.write_text(text, encoding="utf-8")
        print(f"  Saved raw: {raw_path}", flush=True)

    # Parse
    print("[PHASE 2] Parsing...", flush=True)
    zeros = parse_zeros(text)
    if args.max_zeros > 0 and len(zeros) > args.max_zeros:
        zeros = zeros[:args.max_zeros]
    print(f"  Parsed: {len(zeros):,} zeros", flush=True)

    # Validate
    print("[PHASE 3] Validating...", flush=True)
    vinfo = validate(zeros, strict=args.strict)
    print(f"  Range: [{vinfo.get('t_min', 0):.4f}, {vinfo.get('t_max', 0):.4f}]", flush=True)
    print(f"  Gaps: min={vinfo.get('min_gap', 0):.6f}, "
          f"max={vinfo.get('max_gap', 0):.4f}, "
          f"mean={vinfo.get('mean_gap', 0):.4f}", flush=True)
    print(f"  Density ratio: {vinfo.get('density_ratio', 0):.4f}", flush=True)
    if vinfo["issues"]:
        for issue in vinfo["issues"]:
            print(f"  [!] {issue}", flush=True)
    if not vinfo["valid"]:
        print(f"  VALIDATION FAILED", flush=True)
        return 1

    # Unfold
    print("[PHASE 4] Unfolding...", flush=True)
    spacings = compute_unfolded_spacings(zeros)
    print(f"  Spacings: {len(spacings):,} "
          f"(mean={np.mean(spacings):.6f}, "
          f"std={np.std(spacings):.6f})", flush=True)

    # Save
    print("[PHASE 5] Saving...", flush=True)
    zeros_npy = OUTPUT_DIR / f"zeros_odlyzko_{args.table}.npy"
    spacings_npy = OUTPUT_DIR / f"spacings_odlyzko_{args.table}.npy"
    np.save(zeros_npy, zeros)
    np.save(spacings_npy, spacings)
    print(f"  {zeros_npy} ({os.path.getsize(zeros_npy)/1024:.0f} KB)", flush=True)
    print(f"  {spacings_npy} ({os.path.getsize(spacings_npy)/1024:.0f} KB)", flush=True)

    # SHA256
    import hashlib
    sha = hashlib.sha256(zeros.tobytes()).hexdigest()

    # Metadata
    dt = time.time() - t0
    meta = {
        "source": table["url"],
        "table": args.table,
        "description": table["description"],
        "n_zeros": int(len(zeros)),
        "n_spacings": int(len(spacings)),
        "t_range": [float(zeros[0]), float(zeros[-1])],
        "spacings_mean": round(float(np.mean(spacings)), 6),
        "spacings_std": round(float(np.std(spacings)), 6),
        "density_ratio": vinfo.get("density_ratio", 0),
        "max_gap": vinfo.get("max_gap", 0),
        "sha256_zeros": sha,
        "time_s": round(dt, 1),
        "validation": vinfo,
        "files": {
            "zeros_npy": str(zeros_npy),
            "spacings_npy": str(spacings_npy),
            "raw_txt": str(raw_path),
        }
    }

    meta_path = OUTPUT_DIR / f"meta_odlyzko_{args.table}.json"
    meta_path.write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")

    print(f"\n{'='*60}", flush=True)
    print(f"COMPLETE", flush=True)
    print(f"  {len(zeros):,} zeros downloaded + validated + unfolded", flush=True)
    print(f"  Time: {dt:.1f}s", flush=True)
    print(f"  Files: {zeros_npy}, {spacings_npy}", flush=True)
    print(f"  Ready for OUROBOROS HEAVY pipeline", flush=True)
    print(f"{'='*60}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
