"""
poc_25_mersenne.py
==================
Mersenne Spectral POC with the first 25 certified Mersenne prime exponents
vs 25 control exponents (k prime, M_k composite).

Uses the statistic S(u) = sum_gamma w(gamma)*exp(i*gamma*u) with
phase-randomization null, on the Phase-1 dataset (N=332).
"""
from __future__ import annotations
import sys
import io

import json
import math
import os
import numpy as np
from scipy.special import erfc

PROJECT = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis"
import sys; sys.path.insert(0, os.path.join(PROJECT, "scripts"))
from mersenne_spectral_poc import (
    S_of_u, null_distribution, auc_score,
    load_phase1_zeros, WINDOW_MODE, B_NULL,
)

# -- First 25 certified Mersenne prime exponents (historical order) -----------
# Source: GIMPS / https://www.mersenne.org/primes/
MP25 = [
      2,    3,    5,    7,   13,
     17,   19,   31,   61,   89,
    107,  127,  521,  607, 1279,
   2203, 2281, 3217, 4253, 4423,
   9689, 9941,11213,19937,21701,
]

# Controls: k prime such that M_k = 2^k - 1 is COMPOSITE (verified GIMPS/BPSW)
CTRL25 = [
     11,   23,   29,   37,   41,
     43,   47,   53,   59,   67,
     71,   73,   79,   83,   97,
    101,  103,  109,  113,  131,
    137,  139,  149,  151,  157,
]

# ── Dataset ───────────────────────────────────────────────────────────────────
gammas = load_phase1_zeros(
    os.path.join(PROJECT, "results", "riemann", "jules_phase1_full.jsonl")
)
T0, T1  = float(gammas[0]), float(gammas[-1])
N       = len(gammas)

print("="*76)
print("  MERSENNE SPECTRAL POC — 25 Primos Certificados vs 25 Controles")
print(f"  Dataset: N={N}  T=[{T0:.1f},{T1:.1f}]  window={WINDOW_MODE}")
print(f"  Null: phase-randomization  B={B_NULL}")
print("="*76)

# ── Probe function ────────────────────────────────────────────────────────────

def probe(k: int) -> dict:
    Mk  = 2**k - 1
    u   = math.log(Mk)                           # u = log(M_k) ~ k*log(2)
    dev = u - k * math.log(2)                    # deviation from k*log2 (->0 for large k)
    S   = S_of_u(gammas, np.array([u]), T0, T1, WINDOW_MODE)[0]
    obs = float(abs(S))
    nv  = null_distribution(gammas, u, T0, T1, B=B_NULL, seed=k % 99991)
    mu  = float(nv.mean())
    sd  = float(nv.std()) + 1e-9
    z   = (obs - mu) / sd
    return {"k": k, "u": round(u,4), "dev": round(dev,6),
            "obs": round(obs,4), "mu": round(mu,4), "z": round(z,3)}


# ── Run all probes ────────────────────────────────────────────────────────────

all_rows = []
for label, ks in [("mersenne_prime", MP25), ("control", CTRL25)]:
    for k in ks:
        r = probe(k)
        r["label"] = label
        all_rows.append(r)

# FDR — Benjamini-Hochberg
z_arr  = np.array([r["z"] for r in all_rows])
p_vals = 0.5 * erfc(z_arr / math.sqrt(2))
n      = len(p_vals)
order  = np.argsort(p_vals)
q      = np.empty(n)
q[order] = p_vals[order] * n / (np.arange(1, n+1))
q = np.minimum.accumulate(q[::-1])[::-1]
for i, r in enumerate(all_rows):
    r["q"] = round(float(q[i]), 4)


# ── Print ─────────────────────────────────────────────────────────────────────

def section(title):
    print(f"\n  {'─'*70}")
    print(f"  {title}")
    print(f"  {'─'*70}")
    print(f"  {'Type':<16} {'k':>6}  {'u':>10}  {'dev':>8}  "
          f"{'|S|':>6}  {'z':>6}  {'q':>7}")
    print(f"  {'-'*65}")

section("Certified Mersenne Primes (k --> M_k prime)")
for r in [r for r in all_rows if r["label"] == "mersenne_prime"]:
    flag = "***" if r["z"] > 1.5 else ""
    note = "(ampl~0)" if r["k"] > 500 else ""
    print(f"  {'mersenne_prime':<16} {r['k']:>6}  {r['u']:>10.3f}  "
          f"{r['dev']:>+8.5f}  {r['obs']:>6.4f}  {r['z']:>6.2f}  "
          f"{r['q']:>7.4f}  {flag} {note}")

section("Controls (k prime, M_k = 2^k-1 composite)")
for r in [r for r in all_rows if r["label"] == "control"]:
    flag = "***" if r["z"] > 1.5 else ""
    print(f"  {'control':<16} {r['k']:>6}  {r['u']:>10.3f}  "
          f"{r['dev']:>+8.5f}  {r['obs']:>6.4f}  {r['z']:>6.2f}  "
          f"{r['q']:>7.4f}  {flag}")


# ── AUC analysis ──────────────────────────────────────────────────────────────

pos_all = [r["z"] for r in all_rows if r["label"] == "mersenne_prime"]
neg_all = [r["z"] for r in all_rows if r["label"] == "control"]

# Subgroups by k range
def grp(label, k_lo, k_hi):
    return [r["z"] for r in all_rows
            if r["label"] == label and k_lo <= r["k"] <= k_hi]

print(f"\n{'='*76}")
print(f"  AUC ANALYSIS")
print(f"{'='*76}")
print(f"  AUC global (25 vs 25):              {auc_score(pos_all, neg_all):.4f}")
print(f"  AUC k<=127  (primeros 12 MP):       "
      f"{auc_score(grp('mersenne_prime',1,127), neg_all):.4f}")
print(f"  AUC k in [128..1279] (MP 13-15):    "
      f"{auc_score(grp('mersenne_prime',128,1279), neg_all):.4f}")
print(f"  AUC k>1279  (MP 16-25, gigantes):   "
      f"{auc_score(grp('mersenne_prime',1280,99999), neg_all):.4f}")

print(f"\n  INTERPRETACION HONESTA:")
print(f"  ─────────────────────────────────────────────────────────────────")
print(f"  k<=127:   u=log(Mk) in [1.1, 88].  Amplitude detectable (~1e-8 to 1e-2).")
print(f"  k in [521..1279]: u in [361..886].  Amplitude ~1/sqrt(Mk)~1e-80. UNDETECTABLE.")
print(f"  k>2000:   Amplitude essentially zero. Test is pure noise -- validates null.")
print(f"")
print(f"  If AUC(k<=127) > AUC(global): signal comes from small Mersenne primes;")
print(f"  the large ones are pure noise (confirmed by theory). That is CORRECT.")
print(f"  If AUC(global) ~ 0.5: instrument does not discriminate on average,")
print(f"  which is EXPECTED given N=332 and decaying amplitudes.")

# Save
out = {
    "experiment": "poc_25_mersenne",
    "N_zeros": N, "T0": T0, "T1": T1,
    "MP25": MP25, "CTRL25": CTRL25,
    "auc_global": round(auc_score(pos_all, neg_all), 4),
    "auc_k_le_127": round(auc_score(grp("mersenne_prime",1,127), neg_all), 4),
    "rows": all_rows,
}
out_path = os.path.join(PROJECT, "results", "riemann", "poc_25_mersenne.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(f"\n  Saved: {out_path}")
