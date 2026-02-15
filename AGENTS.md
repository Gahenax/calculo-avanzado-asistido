# AGENTS.md - GAHENAX / RIEMANN ZERO MINING

This file provides instructions for autonomous AI agents (like Jules) working on the Riemann Zero Mining task.

## Project Context
This is a high-precision numerical mining project focused on the Riemann Hypothesis (RH). We scan the critical line $s = 1/2 + iT$ for zeros of the Zeta function.

## Main Task: Riemann Zero Mining
Your mission is to execute a systematic scan to find candidates for zeros on the critical line.

### Environment Setup
```bash
pip install mpmath numpy
```

### Execution Protocol
Use the orchestrator script `mine_riemann_zeros.py` to perform the scan in blocks. Each block is governed by a **UA Budget (Athena Units)** to ensure computational efficiency.

```bash
python mine_riemann_zeros.py
```

### Core Logic (Internal)
The orchestrator calls `RIEMANN_ZERO_FILTER_UA_MACRO.py`, which uses a **Tri-Filter Pipeline**:
1.  **L0 (dps=25)**: Fast gating to discard sterile regions.
2.  **L1 (dps=60)**: Signal refinement.
3.  **L2 (dps=120) + Zoom**: High-precision verification of the candidate.

### Output and Reporting
- Results are appended to `riemann_mining_results.jsonl`.
- Each candidate includes:
    - `refined_T`: The precise value of $T$.
    - `verified_s_full`: The absolute value $|\zeta(1/2 + iT)|$ at high precision.
    - `bracket_hint`: (Optional) Interval where $\text{Im}(\zeta)$ changes sign.

### Constraints and Safety
- **No Hallucinations**: Do not claim discovery of zeros without L2 verification.
- **Budget Governance**: Respect the UA budget defined in the macro.
- **Precision**: Always use `mpmath` for Zeta evaluations above L0.

---
*Authorized by Antigravity Core v6.0*
