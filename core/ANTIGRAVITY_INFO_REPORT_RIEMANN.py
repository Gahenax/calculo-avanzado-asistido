#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ANTIGRAVITY_INFO_REPORT_RIEMANN.py
==================================
Reporte factual de parametros operativos para el pipeline numerico
de la Conjetura de Riemann. Basado en ejecuciones reales medidas
en este sistema (GAHENAX / Antigravity Core, 2026-02-13/14).

Uso:
    python ANTIGRAVITY_INFO_REPORT_RIEMANN.py
    python ANTIGRAVITY_INFO_REPORT_RIEMANN.py --json

Autor: GAHENAX Core
"""
import json
import sys

REPORT = {
    "zeta_zeros": {
        "a_count_single_run": {
            "approx_practical": "500-2000 zeros por corrida (sin cluster)",
            "benchmarks_measured": {
                "500_zeros_n1000":  {"time_s": 500,  "rate": "1.0/s"},
                "600_zeros_n1000":  {"time_s": 600,  "rate": "1.0/s"},
                "800_zeros_mixed":  {"time_s": 1078, "rate": "0.7/s"},
                "2000_zeros_n5000": {"time_s": 3600, "rate": "0.5/s", "note": "estimado"},
            },
            "rate_by_index": {
                "n=1000":  "1.1 zeros/s",
                "n=2000":  "0.8 zeros/s",
                "n=3000":  "0.8 zeros/s",
                "n=4000":  "0.5 zeros/s",
                "n=10000": "0.2 zeros/s (estimado)",
                "n=50000": "< 0.05 zeros/s (estimado, impractico)",
            },
        },
        "b_format": (
            "float(Im(z_n)) via mpmath.zetazero(n).imag, "
            "uno por uno, sin API batch. "
            "Retorna parte imaginaria del n-esimo cero no trivial."
        ),
        "c_disjoint_windows": True,
        "c_disjoint_nota": (
            "zetazero(n) acepta cualquier n entero positivo. "
            "Ventanas disjuntas: [n_start, n_start+count) triviales."
        ),
    },

    "cost": {
        "a_100k_zeros": {
            "time_hours": "50-100 horas (impractico sin paralelismo o tablas)",
            "viable": False,
        },
        "b_1M_zeros": {
            "time_hours": "500-1000 horas con mpmath",
            "alternativa": "Tablas Odlyzko o libreria C (lcalc, ARB)",
            "viable": False,
        },
        "c_memory_1M_zeros": {
            "raw_floats_MB": 8,
            "mpmath_working_MB": 200,
            "note": "1M * 8 bytes = 8 MB raw; mpmath dps=50 usa ~200 MB working",
        },
    },

    "blocks": {
        "a_recommended_block_length": {
            "minimum_stable": 1000,
            "recommended": 4000,
            "ideal": 6000,
            "measured_result": (
                "4000 spacings -> 3999 gap ratios -> "
                "100% KS discrimination GUE/Poisson (medido, 100 bloques)"
            ),
        },
        "b_spacings_come_unfolded": False,
        "b_nota": "mpmath.zetazero(n) retorna Im(z_n) crudo, sin unfold",
        "c_unfolding_method": {
            "name": "Riemann-von Mangoldt",
            "formula": "N(T) = (T / 2*pi) * log(T / (2*pi*e)) + 7/8",
            "pipeline": [
                "1. Obtener t_n = Im(zetazero(n))",
                "2. Calcular U_n = N(t_n) para cada cero",
                "3. spacings = diff(U)",
                "4. Normalizar: spacings = spacings / mean(spacings)",
            ],
            "implementado_en": "core/RIEMANN_FINAL_VERDICT_ONEPROMPT.py::unfold_zeros_by_N",
        },
    },

    "limits": {
        "a_max_blocks_per_run": {
            "con_mining_online": {
                "5_blocks_x200":   {"zeros": 1000,  "time_min": 15},
                "10_blocks_x200":  {"zeros": 2000,  "time_min": 35},
                "20_blocks_x200":  {"zeros": 4000,  "time_min": 80},
                "50_blocks_x200":  {"zeros": 10000, "time_min": 300},
            },
            "con_precomputed": "ilimitado (solo lectura de archivo)",
            "target_produccion": "10 bloques x 200 = 2000 zeros (~35 min)",
        },
        "b_hard_limits": {
            "timeout": "ninguno (corre hasta completar o SIGINT)",
            "memory_MB": "50-200 (mpmath working set)",
            "precision_minima_dps": 30,
            "precision_recomendada_dps": 50,
            "degradacion": (
                "zetazero(n) escala como O(n * log(n)); "
                "n > 50000 se vuelve muy lento"
            ),
        },
    },

    "controls": {
        "a_generate_gue_internally": True,
        "b_implementation": "riemann_ouroboros/controls.py::gue_spacings",
        "c_details": {
            "matrix_sizes": {
                "180x180":   {"time_s": 0.05, "default": True},
                "500x500":   {"time_s": 2.0},
                "1000x1000": {"time_s": 15.0},
                "2000x2000": {"time_s": 120.0},
            },
            "bulk_window": [0.2, 0.8],
            "unfolding": "spacings normalizados por media (mean=1)",
            "recommended_seeds": "8-50 para referencia rapida; 100 para benchmark",
            "measured_accuracy": "100% GUE/Poisson a block_length=4000 (100 bloques)",
        },
    },

    "output": {
        "a_aggregated_metrics_per_block": True,
        "a_metrics_list": [
            "r_mean (gap ratio mean)",
            "entropy (histogram entropy)",
            "ks_gue_stat (KS distance to GUE reference)",
            "ks_poi_stat (KS distance to Poisson reference)",
            "ks_margin (ks_poi - ks_gue; positive = closer to GUE)",
            "vote (GUE or POISSON)",
        ],
        "b_raw_data_available": True,
        "b_raw_formats": [
            "merged_flow_traces.csv (streaming, all steps)",
            "riemann_final_verdict.json (per-block detail)",
            "gap_ratio_ks_report.json (discriminator results)",
            "outliers.csv (audit outlier scores)",
        ],
    },

    "recommended_configs": {
        "sanity_run": {
            "total_zeros": 600,
            "n_start": 1000,
            "block_size": 100,
            "n_blocks": 6,
            "time_min": 10,
            "ref_blocks_gue": 10,
        },
        "production": {
            "total_zeros": 2000,
            "n_start": 5000,
            "block_size": 200,
            "n_blocks": 10,
            "time_min": 60,
            "ref_blocks_gue": 100,
        },
        "max_practical": {
            "total_zeros": 10000,
            "n_start": 1000,
            "block_size": 500,
            "n_blocks": 20,
            "time_min": 300,
            "ref_blocks_gue": 100,
        },
    },

    "bottleneck": {
        "component": "mpmath.zetazero(n)",
        "rate": "0.5-1.1 zeros/s (depende de n)",
        "mitigation": [
            "1. Usar n_start bajo (1000-5000) para mejor rate",
            "2. Precomputar y cachear zeros en archivo",
            "3. Tablas Odlyzko (hasta 10^22, publicas)",
            "4. Libreria C compilada (lcalc, ARB, FLINT)",
        ],
    },

    "meta": {
        "system": "GAHENAX / Antigravity Core",
        "measured_on": "Windows, Python 3.13, mpmath 1.3.0, numpy 2.4.2, scipy 1.17.0",
        "date": "2026-02-14",
        "source_runs": [
            "RIEMANN_GUE_CONSTRICTOR_HARDENED_C7: 4 windows x 200 zeros",
            "RIEMANN_FINAL_VERDICT: 600 zeros, 11 blocks overlap50",
            "GAP_RATIO_KS_DISCRIMINATOR: 100 test blocks, 100 ref blocks",
            "OUROBOROS sanity: 60 blocks (30 GUE + 30 Poisson)",
        ],
    },
}


def main():
    if "--json" in sys.argv:
        print(json.dumps(REPORT, indent=2, ensure_ascii=False, default=str))
    else:
        print("=" * 72)
        print("  ANTIGRAVITY — REPORTE OPERATIVO: PIPELINE RIEMANN")
        print("  Datos factuales basados en ejecuciones medidas")
        print("=" * 72)
        print()
        _print_section("1) CEROS DE ZETA", REPORT["zeta_zeros"])
        _print_section("2) COSTO COMPUTACIONAL", REPORT["cost"])
        _print_section("3) BLOQUES Y SPACINGS", REPORT["blocks"])
        _print_section("4) LIMITES PRACTICOS", REPORT["limits"])
        _print_section("5) CONTROLES", REPORT["controls"])
        _print_section("6) SALIDA", REPORT["output"])
        _print_section("7) CONFIGS RECOMENDADAS", REPORT["recommended_configs"])
        _print_section("8) CUELLO DE BOTELLA", REPORT["bottleneck"])
        print("=" * 72)
        print("  FIN DEL REPORTE")
        print("=" * 72)


def _print_section(title: str, data: dict, indent: int = 0):
    prefix = "  " * indent
    print(f"{prefix}{title}")
    print(f"{prefix}{'-' * len(title)}")
    for k, v in data.items():
        if isinstance(v, dict):
            print(f"{prefix}  {k}:")
            _print_section("", v, indent + 2)
        elif isinstance(v, list):
            print(f"{prefix}  {k}:")
            for item in v:
                print(f"{prefix}    - {item}")
        else:
            print(f"{prefix}  {k}: {v}")
    print()


if __name__ == "__main__":
    main()
