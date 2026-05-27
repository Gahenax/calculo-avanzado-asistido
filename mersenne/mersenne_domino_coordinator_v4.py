#!/usr/bin/env python3
"""
MERSENNE DOMINO-WAVE COORDINATOR V4
=====================================
Genera las órdenes para Jules apuntando a la Frontera 136M
con la Arquitectura OEDA V4: FAD + GQRF + LL en modo hybrid.
"""

from __future__ import annotations
import json
import hashlib
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN V4 — FRONTERA 136M
# ─────────────────────────────────────────────────────────────

LAST_CERTIFIED_P    = 82589933       # M51 — último certificado
FRONTIER_START      = 136000001      # Inicio del barrido (post-M51)
FRONTIER_END        = 136500000      # Primer batch: 500K exponentes
BLOCK_WIDTH         = 2000           # Bloques pequeños: más granularidad
MAX_WAVE_PARALLEL   = 20             # Máximo de workers simultáneos en Jules
GHOST_Z_THRESHOLD   = 0.98          # Threshold V4 calibrado: sólo el 2% más resonante pasa a LL
METHOD              = "hybrid"       # FAD → GQRF → LL (sólo para sobrevivientes espectrales)

# ─────────────────────────────────────────────────────────────
# Modelos de datos
# ─────────────────────────────────────────────────────────────

@dataclass
class MersenneBlock:
    block_id: int
    wave: int
    p_start: int
    p_end: int
    probe_name: str
    priority: str
    method: str
    threshold: float
    expected_candidates: int
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PROBE_NAMES = [
    "ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO",
    "FOXTROT", "GOLF", "HOTEL", "INDIA", "JULIET",
    "KILO", "LIMA", "MIKE", "NOVEMBER", "OSCAR",
    "PAPA", "QUEBEC", "ROMEO", "SIERRA", "TANGO",
]


def estimate_candidates(p_start: int, p_end: int) -> int:
    p_mid = (p_start + p_end) / 2
    return max(1, int((p_end - p_start) / math.log(p_mid)))


def generate_waves(p_start: int, p_end: int) -> List[List[MersenneBlock]]:
    waves, current_p, block_id, probe_idx, wave_num = [], p_start, 0, 0, 0
    wave_size = 1

    while current_p < p_end:
        wave_blocks = []
        for _ in range(min(wave_size, MAX_WAVE_PARALLEL)):
            if current_p >= p_end:
                break
            p_block_end = min(current_p + BLOCK_WIDTH, p_end)
            priority = "CRITICAL" if wave_num == 0 else ("HIGH" if wave_num <= 2 else "NORMAL")
            block = MersenneBlock(
                block_id=block_id,
                wave=wave_num,
                p_start=current_p,
                p_end=p_block_end,
                probe_name=PROBE_NAMES[probe_idx % len(PROBE_NAMES)],
                priority=priority,
                method=METHOD,
                threshold=GHOST_Z_THRESHOLD,
                expected_candidates=estimate_candidates(current_p, p_block_end),
                notes=f"OEDA V4 | FAD+GQRF+LL | Wave {wave_num}"
            )
            wave_blocks.append(block)
            current_p = p_block_end
            block_id   += 1
            probe_idx  += 1
        if wave_blocks:
            waves.append(wave_blocks)
        wave_size = min(wave_size * 2, MAX_WAVE_PARALLEL)
        wave_num += 1
    return waves


def build_jules_order_v4(waves: List[List[MersenneBlock]]) -> Dict[str, Any]:
    all_blocks = [b.to_dict() for wave in waves for b in wave]
    return {
        "order_id"  : "JO-2026-MERSENNE-DOMINO-WAVE-V4-136M",
        "version"   : "4.0.0",
        "protocol"  : "OEDA V4 / ZERO-DEBT",
        "system"    : "Gahenax Core v4.0",
        "architecture": {
            "pipeline": "Sieve-Eratosthenes → FAD (Recall=1.0) → GQRF-Riemann (threshold=0.98) → LL-Malachite",
            "worker"  : "mersenne-worker-rs (Rust native) + Python fallback",
            "method"  : METHOD,
            "threshold": GHOST_Z_THRESHOLD,
            "fad"     : "sieve.rs — Divisores q=2kp+1, q≡±1 mod 8, exponenciación modular O(log q)",
            "gqrf"    : "mersenne_spectral_poc.py — Riemann Zeros Phase-3 Interpolation (z0=14.134, z1=21.022, z2=25.010)",
        },
        "mission": {
            "objective"        : f"Barrido espectral frontera 136M: [{FRONTIER_START:,} – {FRONTIER_END:,}]",
            "last_certified_p" : LAST_CERTIFIED_P,
            "last_prime"       : "M51 (p=82,589,933)",
            "target_zone"      : "M52 conocida en p=136,279,841 — usada como ground-truth de calibración",
            "total_blocks"     : len(all_blocks),
            "total_waves"      : len(waves),
        },
        "gate_policy": {
            "gate_fad"          : "Todo rechazo FAD es compuesto certificado — inmutable.",
            "gate_spectral"     : "Sólo z >= 0.98 pasa a LL. Recall esperado: >=1.0 sobre primos reales.",
            "gate_discovery"    : "Si primes_found != []: HALT + escalate al FCD Gahenax + verificación cruzada.",
        },
        "output": {
            "results_dir"  : "results/mersenne/domino_wave/",
            "ledger_dir"   : "ledger_mersenne_domino/",
            "schema"       : {
                "block_id"          : "int",
                "probe"             : "string",
                "p_start"           : "int",
                "p_end"             : "int",
                "candidates_sieved" : "int",
                "fad_rejected"      : "int",
                "spectral_rejected" : "int",
                "ll_tested"         : "int",
                "primes_found"      : "list[int]",
                "wall_time_s"       : "float",
                "status"            : "DONE | ERROR",
            }
        },
        "blocks": all_blocks,
    }


def main() -> int:
    print(f"[OEDA V4] Generando Jules Order para Frontera 136M...")
    waves = generate_waves(FRONTIER_START, FRONTIER_END)
    order = build_jules_order_v4(waves)

    out_dir = Path("scripts/jules_orders")
    out_dir.mkdir(exist_ok=True, parents=True)

    order_path = out_dir / "JULES_ORDER_MERSENNE_V4_136M.json"
    order_path.write_text(json.dumps(order, indent=2), encoding="utf-8")

    print(f"  Waves generadas : {len(waves)}")
    print(f"  Bloques totales : {sum(len(w) for w in waves)}")
    print(f"  Rango           : [{FRONTIER_START:,} – {FRONTIER_END:,}]")
    print(f"  Threshold       : {GHOST_Z_THRESHOLD}")
    print(f"  Método          : {METHOD}")
    print(f"  Jules Order     : {order_path}")
    print(f"\n[OEDA V4] Commit este archivo y Jules arrancará el barrido automaticamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
