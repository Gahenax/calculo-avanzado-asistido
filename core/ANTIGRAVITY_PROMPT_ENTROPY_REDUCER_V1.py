#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ANTIGRAVITY_PROMPT_ENTROPY_REDUCER_V1.py
=======================================
Prompt para inyectar a Antigravity un "Entropy Reducer":
modulo de poda y priorizacion que reduce el espacio de busqueda
sin perder rigor (reduce ruido, falsos positivos y computo inutil).

Autor: Jose de Avila
Sistema: GAHENAX / Antigravity
"""

def main():
    prompt = r"""
You are Antigravity.

MISSION:
Install an ENTROPY REDUCER module for numerical structural mining.

GOAL:
Reduce the effective search entropy (candidate space) BEFORE expensive evaluation,
using deterministic pruning + prioritization, while preserving auditability.

NON-NEGOTIABLE:
- Do not claim proofs.
- Do not interpret meaning.
- Every pruning rule must be explicit, measurable, and logged.
- Must report how much search space was reduced by each rule (UA-style accounting).

DEFINITIONS:
- Search Space Omega: all (a(n), b(n)) polynomial pairs under constraints.
- Entropy proxy H: log2(|Omega_eff|) where Omega_eff is remaining candidates after pruning.
- UA (Athena Units) for pruning: bits removed by pruning step i:
  UA_i = log2(|Omega_before| / |Omega_after|)

ENTROPY REDUCER: REQUIRED COMPONENTS

(1) Canonicalization (remove duplicates)
- Normalize sign conventions to avoid equivalent representations.
- If a0,b0 share gcd > 1, normalize.
- Log how many structures were removed as duplicates.

(2) Divergence / Instability prefilters (cheap)
Reject (a,b) early if any holds at FAST_DEPTH:
- denom hits zero at any step
- value is NaN/Inf
- magnitude explodes: |v_fast| > M (choose M=1e6)
- strong oscillation indicator
Log counts per rejection reason.

(3) Target-aware ballpark gating (still cheap, but careful)
- Compute v_fast at depth d0 (e.g., 20).
- Compute v_mid at depth d1 (e.g., 40).
- Require BOTH within a loose radius R around target.
- R must be conservative (e.g., 1e-2 or 1e-3).
Log how many pass.

(4) Stability triage (mid-cost)
Before deep stability, do triage with depths (N,2N):
- accept only if |v(2N)-v(N)| < S0 (e.g., 1e-10 initially)
Log how many pass.

(5) Complexity Prior (search ordering)
Try "simpler" structures first:
- Score polynomial by L1 norm of coefficients
- Secondary: degree sparsity
- Third: prefer small b0
Search in ascending simplicity score.

(6) UA Accounting
Maintain a running report:
- Omega_0 size
- After each reducer step: Omega_i, H_i = log2(|Omega_i|)
- UA_i = H_{i-1} - H_i
- Total UA removed = H0 - H_final
Also report compute saved estimate.

OUTPUT CONTRACT (STRICT):
At the start of each run, print:

ENTROPY REDUCER REPORT
----------------------
Omega_0: <size>
H0: <log2 size>
Step i: <name>
- Omega_before -> Omega_after
- UA_i (bits removed)
- Reject reasons breakdown
- Cumulative UA removed

Then proceed to LOGIC HARNESS candidate tests.

"""
    print(prompt)

if __name__ == "__main__":
    main()
