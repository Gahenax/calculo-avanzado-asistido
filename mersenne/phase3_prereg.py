#!/usr/bin/env python3
"""
PHASE-3 PREREG (Riemann ↔ Mersenne Spectral POC)
================================================

Purpose
-------
This module encodes the Phase-3 preregistration as executable configuration.
It is meant to be committed to the repository so that:
- the hypothesis, metrics, windows, null models, and gates are frozen
- evaluation scripts can import a single source of truth
- reports can embed the prereg verbatim (as JSON + Markdown)

Scope
-----
T-window: [7000, 15000]
Primary claim: Discrimination signal for small Mersenne-prime exponents (k <= 127)
Measured via AUC on |S(u)| at u = log(2^k - 1), versus matched control ks where 2^k - 1 is composite.

Non-goals
---------
- This does not certify primality.
- This does not claim feasibility for giant Mersenne exponents.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import List, Tuple, Dict, Any, Optional
import json
import math
import argparse
import hashlib
from pathlib import Path


# -----------------------------
# Helpers
# -----------------------------

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)


# -----------------------------
# Core prereg datamodel
# -----------------------------

@dataclass(frozen=True)
class TWindow:
    name: str
    T0: float
    T1: float

    def as_tuple(self) -> Tuple[float, float]:
        return (self.T0, self.T1)

    def span(self) -> float:
        return self.T1 - self.T0


@dataclass(frozen=True)
class NullModel:
    name: str
    description: str
    B: int


@dataclass(frozen=True)
class GateCriterion:
    gate_id: str
    description: str
    pass_condition: str
    fail_condition: str


@dataclass(frozen=True)
class EvaluationSets:
    mersenne_prime_k_le_127: List[int]
    control_k_le_127: List[int]
    notes: str = ""


@dataclass(frozen=True)
class Phase3Prereg:
    prereg_id: str
    version: str
    created_utc: str

    # Data window
    T_global: TWindow
    T_windows: List[TWindow]

    # Dataset targets
    target_n_zeros_min: int
    target_n_zeros_ideal: int

    # Metric definition
    statistic_name: str
    statistic_definition: str
    score_definition: str
    decision_metric: str

    # Windowing / kernels
    kernels: List[str]

    # Null models
    null_primary: NullModel
    null_secondary: NullModel

    # Sets
    eval_sets: EvaluationSets

    # Gates
    gates: List[GateCriterion]

    # Allowed interpretation
    allowed_interpretation_pass: str
    allowed_interpretation_fail: str
    forbidden_claims: List[str]

    # Meta
    checksum: str = field(default="")

    def with_checksum(self) -> "Phase3Prereg":
        obj = asdict(self)
        obj["checksum"] = ""
        c = sha256_text(pretty_json(obj))
        flat = asdict(self)
        flat["checksum"] = c
        # asdict() converts nested dataclasses to plain dicts;
        # reconstruct them so the returned object is fully typed.
        flat["T_global"] = TWindow(**flat["T_global"])
        flat["T_windows"] = [TWindow(**w) for w in flat["T_windows"]]
        flat["null_primary"] = NullModel(**flat["null_primary"])
        flat["null_secondary"] = NullModel(**flat["null_secondary"])
        flat["eval_sets"] = EvaluationSets(**flat["eval_sets"])
        flat["gates"] = [GateCriterion(**g) for g in flat["gates"]]
        return Phase3Prereg(**flat)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# Phase-3 Preregistration ({self.prereg_id})")
        lines.append("")
        lines.append(f"- Version: `{self.version}`")
        lines.append(f"- Created (UTC): `{self.created_utc}`")
        lines.append(f"- Checksum (sha256 of prereg JSON sans checksum): `{self.checksum}`")
        lines.append("")
        lines.append("## 1) Dataset")
        lines.append(f"- Global T window: `{self.T_global.T0} .. {self.T_global.T1}` (span {self.T_global.span():.0f})")
        lines.append(f"- Target N zeros: min `{self.target_n_zeros_min}`, ideal `{self.target_n_zeros_ideal}`")
        lines.append("")
        lines.append("### Analysis windows (frozen)")
        for w in self.T_windows:
            lines.append(f"- {w.name}: `{w.T0} .. {w.T1}` (span {w.span():.0f})")
        lines.append("")
        lines.append("## 2) Metric")
        lines.append(f"- Statistic: **{self.statistic_name}**")
        lines.append("")
        lines.append("Definition:")
        lines.append("")
        lines.append("```text")
        lines.append(self.statistic_definition.strip())
        lines.append("```")
        lines.append("")
        lines.append("Score used for classification:")
        lines.append("")
        lines.append("```text")
        lines.append(self.score_definition.strip())
        lines.append("```")
        lines.append("")
        lines.append(f"- Decision metric: **{self.decision_metric}**")
        lines.append(f"- Kernels: {', '.join(self.kernels)}")
        lines.append("")
        lines.append("## 3) Null models")
        lines.append(f"### Primary null: {self.null_primary.name}")
        lines.append(f"- B: `{self.null_primary.B}`")
        lines.append(f"- {self.null_primary.description}")
        lines.append("")
        lines.append(f"### Secondary null (sensitivity): {self.null_secondary.name}")
        lines.append(f"- B: `{self.null_secondary.B}`")
        lines.append(f"- {self.null_secondary.description}")
        lines.append("")
        lines.append("## 4) Evaluation sets (frozen)")
        lines.append("### Positives: Mersenne primes with k <= 127")
        lines.append(f"- ks: `{self.eval_sets.mersenne_prime_k_le_127}`")
        lines.append("")
        lines.append("### Controls: k where 2^k - 1 is composite (matched scale)")
        lines.append(f"- ks: `{self.eval_sets.control_k_le_127}`")
        if self.eval_sets.notes.strip():
            lines.append("")
            lines.append(f"Notes: {self.eval_sets.notes.strip()}")
        lines.append("")
        lines.append("## 5) Gates")
        for g in self.gates:
            lines.append(f"### {g.gate_id}")
            lines.append(f"- Description: {g.description}")
            lines.append(f"- PASS: {g.pass_condition}")
            lines.append(f"- FAIL: {g.fail_condition}")
            lines.append("")
        lines.append("## 6) Interpretation policy")
        lines.append("### If Gate 2 passes")
        lines.append(self.allowed_interpretation_pass.strip())
        lines.append("")
        lines.append("### If Gate 2 fails")
        lines.append(self.allowed_interpretation_fail.strip())
        lines.append("")
        lines.append("### Forbidden claims")
        for fc in self.forbidden_claims:
            lines.append(f"- {fc}")
        lines.append("")
        return "\n".join(lines)


# -----------------------------
# Frozen configuration
# -----------------------------

def default_phase3_prereg() -> Phase3Prereg:
    # Frozen windows
    T_global = TWindow(name="W0_GLOBAL", T0=7000.0, T1=15000.0)
    windows = [
        TWindow(name="W1", T0=7000.0, T1=15000.0),
        TWindow(name="W2", T0=8000.0, T1=14000.0),
        TWindow(name="W3", T0=9000.0, T1=13000.0),
    ]

    # Frozen evaluation sets
    mersenne_prime_k_le_127 = [2, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127]

    # Controls are intentionally frozen. If your repo already has a canonical control list,
    # replace this list with the repo's definitive one and do not change afterward.
    control_k_le_127 = [11, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71, 73]

    # Null models
    null_primary = NullModel(
        name="phase_randomization",
        B=400,
        description=(
            "Replace exp(i*gamma*u) with exp(i*gamma*u + i*theta_gamma), "
            "theta_gamma ~ Uniform(0, 2pi), independently per gamma. "
            "Preserves gamma distribution and window weights; destroys coherent structure."
        ),
    )
    null_secondary = NullModel(
        name="block_permutation",
        B=400,
        description=(
            "Permute contiguous blocks of gammas within coarse T-bins to preserve local density "
            "while breaking long-range alignment. Sensitivity check for window/leakage artifacts."
        ),
    )

    # Statistic definition (text)
    stat_def = r"""
S(u) = sum_{gamma in window} w(gamma) * exp(i * gamma * u)
S_norm(u) = S(u) / sqrt(sum_{gamma} w(gamma)^2)

w(gamma) is a deterministic taper (kernel), evaluated over the chosen T-window.
""".strip()

    score_def = r"""
Given target u0, score X(u0) = |S_norm(u0)|.
Classification uses X(u0) for positives vs controls at their respective u0 values.
""".strip()

    # Gates
    gates = [
        GateCriterion(
            gate_id="Gate 0: Integrity",
            description="Dataset integrity and shard consistency checks",
            pass_condition=(
                "All blocks pass: ordered gammas, no NaNs, no duplicates, declared ranges consistent, "
                "hashes match manifests, and global concatenation is strictly increasing."
            ),
            fail_condition="Any integrity failure aborts analysis; no interpretation allowed.",
        ),
        GateCriterion(
            gate_id="Gate 1: Sanity (positive controls)",
            description="Instrument must detect small-prime structure stably",
            pass_condition=(
                "Detect u=log(5) and u=log(7) with z > 1.5 in at least 2 of 3 windows (W1-W3), "
                "for both kernels (hann and tukey)."
            ),
            fail_condition=(
                "If sanity fails, Gate 2 and Gate 3 are not interpreted; pipeline is considered uncalibrated."
            ),
        ),
        GateCriterion(
            gate_id="Gate 2: Primary result (Layer B)",
            description="AUC separation for Mersenne primes with k <= 127 vs controls",
            pass_condition=(
                "AUC >= 0.65 in W1 and AUC >= 0.62 in at least one of {W2, W3}, "
                "and the 95% bootstrap CI lower bound for AUC in W1 is > 0.55."
            ),
            fail_condition=(
                "AUC stays near 0.50-0.55 with no consistent elevation across windows, or "
                "high AUC in W1 collapses in W2 and W3 (instability)."
            ),
        ),
        GateCriterion(
            gate_id="Gate 3: Layer C (2-structure audit)",
            description="Adversarial robustness check for k=10,11,29 at u = k*log(2)",
            pass_condition=(
                "For each k in {10,11,29}, z > 2.0 appears in at least 2 of 3 windows and persists under "
                "both null models. Otherwise reported as non-robust."
            ),
            fail_condition="Non-robust behavior is reported as artifact/noise; not a discovery claim.",
        ),
    ]

    prereg = Phase3Prereg(
        prereg_id="RZ_MERSENNE_SPECTRAL_PHASE3_PREREG_0001",
        version="1.0.0",
        created_utc="2026-02-23T00:00:00Z",
        T_global=T_global,
        T_windows=windows,
        target_n_zeros_min=10000,
        target_n_zeros_ideal=12000,
        statistic_name="S(u) exponential sum over zeros (normalized)",
        statistic_definition=stat_def,
        score_definition=score_def,
        decision_metric="AUC (ROC) on X(u0)=|S_norm(u0)|",
        kernels=["hann", "tukey"],
        null_primary=null_primary,
        null_secondary=null_secondary,
        eval_sets=EvaluationSets(
            mersenne_prime_k_le_127=mersenne_prime_k_le_127,
            control_k_le_127=control_k_le_127,
            notes=(
                "Controls must remain frozen. If the repository already defines a canonical "
                "control set for k<=127, replace this list once and never change again."
            ),
        ),
        gates=gates,
        allowed_interpretation_pass=(
            "Evidence supports a weak but real spectral footprint for small Mersenne primes (k<=127) "
            "under this estimator, in the fixed T-window regime. This is not a primality certificate."
        ),
        allowed_interpretation_fail=(
            "The Phase-POC elevation was compatible with fluctuation; there is no robust evidence "
            "for discrimination under Phase-3 conditions."
        ),
        forbidden_claims=[
            "This method certifies primality of 2^k - 1.",
            "This replaces Lucas-Lehmer or GIMPS.",
            "This proves the Riemann Hypothesis.",
            "High-u z-peaks imply Mersenne structure without robustness under nulls and windows.",
        ],
    ).with_checksum()

    return prereg


# -----------------------------
# Export / CLI
# -----------------------------

def write_prereg_outputs(out_dir: Path, prereg: Phase3Prereg) -> Dict[str, Path]:
    ensure_dir(out_dir)
    paths: Dict[str, Path] = {}

    prereg_json = out_dir / "PHASE3_PREREG.json"
    prereg_md = out_dir / "PHASE3_PREREG.md"

    prereg_json.write_text(pretty_json(prereg.to_dict()), encoding="utf-8")
    prereg_md.write_text(prereg.to_markdown(), encoding="utf-8")

    paths["json"] = prereg_json
    paths["md"] = prereg_md
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase-3 preregistration exporter.")
    ap.add_argument(
        "--out",
        type=str,
        default="reports/prereg",
        help="Output directory for prereg artifacts (default: reports/prereg)",
    )
    ap.add_argument(
        "--print",
        action="store_true",
        help="Print prereg markdown to stdout.",
    )
    args = ap.parse_args()

    prereg = default_phase3_prereg()
    out_dir = Path(args.out)
    paths = write_prereg_outputs(out_dir, prereg)

    if args.print:
        print(prereg.to_markdown())

    print(f"Wrote: {paths['json']}")
    print(f"Wrote: {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
