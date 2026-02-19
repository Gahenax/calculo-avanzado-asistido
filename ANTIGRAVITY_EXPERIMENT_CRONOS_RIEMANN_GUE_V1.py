#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ANTIGRAVITY_EXPERIMENT_CRONOS_RIEMANN_GUE_V1.py

Imprime un plan JSON para Antigravity: experimento reproducible que prueba/falsa
la tesis Cronos (Floquet) <-> Riemann (GUE) vía estadísticas espectrales.

No ejecuta simulaciones aquí; genera un plan orquestable con barridos, métricas
y criterios (aceptación/muerte) para que Antigravity lo ejecute en su runtime.

Uso:
  python ANTIGRAVITY_EXPERIMENT_CRONOS_RIEMANN_GUE_V1.py > plan.json
"""

import json
from datetime import datetime, timezone


def build_plan():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    plan = {
        "meta": {
            "plan_id": "CRONOS_RIEMANN_GUE_VALIDATION_V1",
            "created_utc": now,
            "owner": "Jose de Avila",
            "intent": "EXPERIMENT",
            "rigor": "HIGH",
            "reproducibility": "STRICT",
            "notes": [
                "This plan aims to falsify, not confirm, the thesis.",
                "Primary metric: r-mean of spacing ratios.",
                "Secondary metric: KS distance vs GUE surmise for quick semaforo.",
                "Cronos is Floquet: phases on circle. Use circular spacings.",
                "Riemann uses unfolding with Riemann-von Mangoldt.",
            ],
        },

        "hypotheses": {
            "H0": "Cronos chaotic regime does NOT match GUE/CUE-like statistics; r_mean remains near Poisson/GOE across W.",
            "H1": "Cronos exhibits a disorder-tuned crossover: high W -> Poisson-like (r~0.386), low W -> CUE/GUE-like (r~0.60).",
            "H2": "Riemann zeros in the tested block show GUE-like repulsion (r~0.60) and are distinguishable from Poisson.",
            "H3": "In Cronos, the 'melted' (chaotic) side aligns with Riemann's GUE-like signature more than the MBL side."
        },

        "variables": {
            "control": {
                "J": 1.0,
                "t2": 1.0,
                "eps_frac_pi": 0.1,
                "g": 0.2,
                "boundary": "periodic",
            },
            "sweeps": {
                "L_list": [8, 9, 10, 11, 12],
                "W_list": [0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0],
                "seeds_per_point": 12,
            },
            "riemann_blocks": {
                "blocks": [
                    {"name": "block_1000_1370", "n_start": 1000, "n_end": 1370}
                ],
                "unfolding": "riemann_von_mangoldt",
            },
        },

        "metrics": {
            "primary": [
                {
                    "name": "r_mean",
                    "definition": "mean(min(s_n,s_{n+1})/max(s_n,s_{n+1}))",
                    "expected": {
                        "poisson": 0.386,
                        "goe": 0.536,
                        "gue_or_cue": 0.60
                    }
                }
            ],
            "secondary": [
                {
                    "name": "ks_gue",
                    "definition": "KS distance between empirical CDF(s_norm) and GUE surmise CDF",
                    "direction": "lower_is_better"
                },
                {
                    "name": "p2_over_p1",
                    "definition": "subharmonic power ratio for DTC order parameter Mz(n) (optional)",
                    "direction": "higher_is_more_subharmonic"
                },
                {
                    "name": "wasserstein_spacing",
                    "definition": "Wasserstein distance between spacing distributions (Cronos vs Riemann) after normalization",
                    "direction": "lower_is_more_aligned"
                }
            ]
        },

        "acceptance_criteria": {
            "A1_crossover_exists": {
                "statement": "There exists W_high and W_low such that r_mean(W_high) <= 0.45 and r_mean(W_low) >= 0.57 for at least one L in L_list.",
                "fail_if_not_met": True
            },
            "A2_riemann_gue": {
                "statement": "Riemann r_mean in the tested block is >= 0.57 and KS <= 0.12.",
                "fail_if_not_met": True
            },
            "A3_alignment": {
                "statement": "For some (L, W_low), Wasserstein(Cronos spacing, Riemann spacing) is smaller than Wasserstein(Cronos spacing at W_high, Riemann spacing).",
                "fail_if_not_met": False
            }
        },

        "kill_criteria": [
            {
                "id": "K1",
                "if": "cronossweep.completed and not acceptance.A1_crossover_exists",
                "action": "ABORT_EXPERIMENT",
                "reason": "No Poisson->GUE/CUE crossover detected within tested W/L grid."
            },
            {
                "id": "K2",
                "if": "riemannstats.completed and not acceptance.A2_riemann_gue",
                "action": "ABORT_EXPERIMENT",
                "reason": "Riemann block did not show GUE-like signature; dataset/pipeline likely compromised."
            }
        ],

        "logging": {
            "ledger_event_type": "POC_SCIENTIFIC_ORCHESTRATION",
            "run_id_template": "{plan_id}:{timestamp}:{hash}",
            "artifacts": [
                "results/riemann_stats.json",
                "results/cronos_grid_stats.jsonl",
                "results/alignment_report.json",
                "plots/spacings_histograms.png",
                "plots/rmean_phase_map.png"
            ],
            "schema_version": "1.0"
        },

        "resource_budget": {
            "ua_budget_total": 2000,
            "ua_budget_soft": 1600,
            "per_task_ua_cap": 500,
            "timeouts_sec": {
                "riemann_stats": 300,
                "cronos_point": 120,
                "cronos_grid": 2400,
                "alignment": 600
            }
        },

        "tasks": [
            {
                "task_id": "T1_RIEMANN_STATS",
                "type": "python_module",
                "entrypoint": "RIEMANN_GUE_STATS.py",
                "inputs": {
                    "source": "riemann_mining_results.jsonl",
                    "block": "block_1000_1370"
                },
                "outputs": {
                    "report_path": "results/riemann_stats.json"
                },
                "checks": [
                    "report.r_mean >= 0.57",
                    "report.ks_gue <= 0.12"
                ]
            },
            {
                "task_id": "T2_CRONOS_GRID",
                "type": "python_module",
                "entrypoint": "TIME_CRYSTAL_FLOQUET_SPECTRUM.py",
                "inputs": {
                    "L_list": "{variables.sweeps.L_list}",
                    "W_list": "{variables.sweeps.W_list}",
                    "seeds_per_point": "{variables.sweeps.seeds_per_point}",
                    "control": "{variables.control}"
                },
                "outputs": {
                    "grid_path": "results/cronos_grid_stats.jsonl"
                },
                "checks": [
                    "grid.contains_poisson_like_point",
                    "grid.contains_gue_like_point"
                ]
            },
            {
                "task_id": "T3_ALIGNMENT",
                "type": "python_module",
                "entrypoint": "ALIGN_SPACING_DISTS.py",
                "inputs": {
                    "riemann_report": "results/riemann_stats.json",
                    "cronos_grid": "results/cronos_grid_stats.jsonl",
                    "method": "wasserstein",
                    "select": {
                        "cronos_lowW_candidate": {"r_mean_min": 0.57},
                        "cronos_highW_candidate": {"r_mean_max": 0.45}
                    }
                },
                "outputs": {
                    "alignment_path": "results/alignment_report.json"
                },
                "checks": [
                    "alignment.lowW_closer_than_highW == true"
                ]
            },
            {
                "task_id": "T4_REPORT_AND_PLOTS",
                "type": "python_module",
                "entrypoint": "MAKE_FINAL_REPORT.py",
                "inputs": {
                    "riemann_report": "results/riemann_stats.json",
                    "cronos_grid": "results/cronos_grid_stats.jsonl",
                    "alignment": "results/alignment_report.json"
                },
                "outputs": {
                    "final_report_path": "results/final_report.json",
                    "plots_dir": "plots/"
                }
            },
            {
                "task_id": "T5_LEDGER_COMMIT",
                "type": "ledger_commit",
                "inputs": {
                    "event_type": "{logging.ledger_event_type}",
                    "status": "CLOSED_SUCCESS",
                    "artifacts": "{logging.artifacts}",
                    "summary": {
                        "thesis": "Cronos chaotic regime aligns with Riemann GUE-like stats; MBL diverges to Poisson.",
                        "acceptance": "{acceptance_criteria}",
                        "kill_criteria": "{kill_criteria}"
                    }
                }
            }
        ],

        "execution_order": [
            "T1_RIEMANN_STATS",
            "T2_CRONOS_GRID",
            "T3_ALIGNMENT",
            "T4_REPORT_AND_PLOTS",
            "T5_LEDGER_COMMIT"
        ]
    }

    return plan


def main():
    plan = build_plan()
    print(json.dumps(plan, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
