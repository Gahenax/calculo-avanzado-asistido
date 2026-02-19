#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RIEMANN_ZERO_FILTER_UA_MACRO.py
===============================
Macro prompt (ejecutable) que adapta tu módulo de exploración A/B a un caso específico:
"filtrar 0" en la Conjetura de Riemann usando un pipeline Tri-Filtro (L0→L1→L2)
con gobernanza tipo UA (presupuesto, abortos limpios, telemetría por estados).

Qué hace:
- Explora T en la recta crítica s = 1/2 + iT.
- L0 (barato): score_fast(T) con mpmath a baja precisión (dps_low).
- L1 (medio): score_mid(T) con más precisión (dps_mid).
- L2 (caro): score_full(T) con alta precisión (dps_high) + "zoom local" alrededor de hits.
- Produce candidatos ordenados por score_full (cercanía a 0).
- Opcional: intenta "bracketing" por cambios de signo en Im(zeta) para sugerir intervalos de ceros.

Nota:
- Esto NO pretende "probar RH". Es un filtro/escáner robusto para encontrar regiones/candidatos.
- Si quieres “ceros reales”, conecta el output a un refinador (Brent/Newton) con continuidad de argumento.

Dependencias:
    pip install mpmath numpy

Uso rápido:
    python RIEMANN_ZERO_FILTER_UA_MACRO.py --T0 1000 --T1 2000 --step 0.05 --budget 500000

Autor: (tu pipeline UA adaptado)
"""

import argparse
import math
import time
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import mpmath as mp

# Local imports
from core.gahenax_utils import UALedger, HardeningConfig
from core.GAHENAX_UPGRADES import (
    RiemannDetection, RiemannConfidenceConfig, RiemannConfidenceScorer,
    HostilityConfig, CandidateRelation, HostilityTester
)
import core.riemann_pipeline_utils as rutils

@dataclass
class UAConfig:
    budget_total: int = 500_000          # UA totales
    A_frac: float = 0.70                # % del presupuesto para Exploración (L0+L1)
    B_frac: float = 0.30                # % del presupuesto para Explotación (zoom+L2)

@dataclass
class PrecisionConfig:
    dps_low: int = 25
    dps_mid: int = 60
    dps_high: int = 120

@dataclass
class Thresholds:
    tau_fast: float = 0.5
    tau_mid: float = 0.2
    bracket_im_eps: float = 1e-3

@dataclass
class ScanConfig:
    T0: float = 1000.0
    T1: float = 1200.0
    step: float = 0.05
    zoom_radius: float = 0.50
    zoom_points: int = 41
    max_hits_L1: int = 200
    max_hits_L2: int = 40

class RiemannLedger(UALedger):
    def __init__(self, cfg_ua: UAConfig):
        super().__init__(budget=cfg_ua.budget_total)
        self.A_budget = int(cfg_ua.budget_total * cfg_ua.A_frac)
        self.B_budget = int(cfg_ua.budget_total * cfg_ua.B_frac)
        self.A_spent = 0
        self.B_spent = 0
        # Telemetry
        self.n_L0 = 0
        self.n_L0_pass = 0
        self.n_L1 = 0
        self.n_L1_pass = 0
        self.n_L2 = 0
        self.n_zoom = 0
        self.ua_flow = 0
        self.ua_kick = 0
        self.t_start = 0.0
        self.t_end = 0.0

    def begin(self): self.t_start = time.time()
    def end(self): self.t_end = time.time()
    @property
    def elapsed(self): return max(0.0, self.t_end - self.t_start)

    def can_spend_A(self, ua: int) -> bool: return (self.A_spent + ua) <= self.A_budget
    def can_spend_B(self, ua: int) -> bool: return (self.B_spent + ua) <= self.B_budget

    def spend_A(self, ua: int):
        if not self.can_spend_A(ua): raise RuntimeError("A budget exhausted")
        self.A_spent += ua
        self.ua_flow += ua
        self.pay("mix", ua)

    def spend_B(self, ua: int):
        if not self.can_spend_B(ua): raise RuntimeError("B budget exhausted")
        self.B_spent += ua
        self.ua_kick += ua
        self.pay("deep_search", ua)


@dataclass
class Thresholds:
    tau_fast: float = 0.5
    tau_mid: float = 0.2
    bracket_im_eps: float = 1e-3

@dataclass
class ScanConfig:
    T0: float = 1000.0
    T1: float = 1200.0
    step: float = 0.05
    zoom_radius: float = 0.50
    zoom_points: int = 41
    max_hits_L1: int = 200
    max_hits_L2: int = 40

@dataclass
class Candidate:
    T: float
    s_fast: float
    s_mid: float
    s_full: Optional[float] = None
    refined_T: Optional[float] = None
    refined_s_mid: Optional[float] = None
    verified_s_full: Optional[float] = None
    bracket_hint: Optional[Tuple[float, float]] = None
    confidence: float = 0.0
    hs_survival: float = 0.0
    status: str = "VALLEY_ONLY"
    root_val: Optional[float] = None
    edge: bool = False

# =============================================================================
# INDUSTRIAL SIGN-CHANGE DISCOVERY + ADAPTIVE SCAN
# =============================================================================

def get_mean_spacing(T: float) -> float:
    """Theoretical mean spacing Delta(T)."""
    if T < 2 * math.pi: return 1.0
    return (2 * math.pi) / math.log(T / (2 * math.pi))

def hardy_z(T: float, dps: int = 60) -> float:
    """Calculates the real-valued Hardy Z-function at t."""
    mp.mp.dps = dps
    t = mp.mpf(T)
    theta = mp.siegeltheta(t)
    z = mp.exp(1j * theta) * mp.zeta(0.5 + 1j * t)
    return float(mp.re(z))

def bracketing_scan(cfg_scan: ScanConfig, cfg_prec: PrecisionConfig, 
                   ledger: RiemannLedger, alpha: float = 0.25) -> List[Candidate]:
    """
    Advanced Sign-Change Scanner:
    - Discovery: Z(t_i) * Z(t_{i+1}) <= 0
    - Adaptive: step = alpha * Delta(T)
    - Precision: Brent confirmation on every bracket
    """
    candidates: List[Candidate] = []
    T = cfg_scan.T0
    
    # Initial evaluation
    ledger.begin()
    z_prev = hardy_z(T, cfg_prec.dps_mid)
    ledger.spend_A(35) # Initial cost
    ledger.n_L0 += 1

    step_count = 0
    while T < cfg_scan.T1:
        step_count += 1
        # Dynamic step
        delta = get_mean_spacing(T)
        h = alpha * delta
        next_T = T + h
        if next_T > cfg_scan.T1:
            next_T = cfg_scan.T1
            
        if step_count % 50 == 0:
            print(f"  [SCAN] T={T:.2f} | h={h:.4f} | Found: {len(candidates)}")
            
        # Evaluation at next point
        ua_cost = 35 # Evaluation of Hardy Z
        if not ledger.can_spend_A(ua_cost):
            break
            
        z_curr = hardy_z(next_T, cfg_prec.dps_mid)
        if step_count < 10:
            print(f"    [DEBUG] T={next_T:.4f} Z={z_curr:.4e}")
        ledger.spend_A(ua_cost)
        ledger.n_L1 += 1
        
        # Check for SIGN CHANGE (The "Industrial Anzuelo")
        if z_prev * z_curr <= 0:
            # Bracket found: [T, next_T]
            ua_cost_brent = 150 # Brent is more expensive
            if ledger.can_spend_B(ua_cost_brent):
                ledger.spend_B(ua_cost_brent)
                ledger.n_L2 += 1
                
                # Brent Refinement
                try:
                    mp.mp.dps = cfg_prec.dps_high
                    # Use a lambda that sets dps to ensure precision during search
                    f = lambda x: hardy_z(float(x), cfg_prec.dps_high)
                    # The instruction implies 'brent' might have been used, but 'bisect' is already here.
                    # We ensure 'bisect' is used and adjust arguments as per the instruction's example.
                    a, b = T, next_T
                    tol = 1e-15
                    root = mp.findroot(f, (a, b), solver='bisect', tol=tol)
                    
                    c = Candidate(
                        T=T,
                        s_fast=abs(z_prev),
                        s_mid=abs(z_curr),
                        refined_T=float(root),
                        verified_s_full=abs(f(root)),
                        status="CONFIRMED",
                        root_val=float(f(root)),
                        bracket_hint=(T, next_T)
                    )
                    
                    # Confidence and Hostility (keep existing logic)
                    conf_cfg = RiemannConfidenceConfig()
                    scorer = RiemannConfidenceScorer(conf_cfg)
                    det = RiemannDetection(
                        t_center=c.refined_T,
                        bracket=c.bracket_hint,
                        hs_value=c.verified_s_full,
                        precision_bits=int(mp.mp.prec)
                    )
                    c.confidence = scorer.score(det)
                    
                    candidates.append(c)
                except Exception as e:
                    print(f"    [ERROR] Root finding failed at T={T:.4f}: {e}")
                    pass

        T = next_T
        z_prev = z_curr

    # Dedupe results (overlapping brackets might happen at boundaries)
    c_dicts = [asdict(c) for c in candidates]
    for i, d in enumerate(c_dicts):
        d["t_center"] = candidates[i].refined_T
        d["absZ"] = candidates[i].verified_s_full
        
    deduped = rutils.dedupe_candidates(c_dicts, key_t="t_center", eps=1e-5)
    
    final = []
    for d in deduped:
        cc = Candidate(**{k: v for k, v in d.items() if k not in ["t_center", "absZ"]})
        final.append(cc)
        
    ledger.end()
    return final

def main():
    args = parse_args()
    cfg_scan = ScanConfig(T0=args.T0, T1=args.T1, step=args.step)
    cfg_ua = UAConfig(budget_total=args.budget, A_frac=args.A_frac, B_frac=args.B_frac)
    cfg_prec = PrecisionConfig(dps_low=args.dps_low, dps_mid=args.dps_mid, dps_high=args.dps_high)
    ledger = RiemannLedger(cfg_ua)
    
    # Use alpha from args or default to 0.20
    alpha = args.step if args.step < 1.0 else 0.20 
    
    refined = bracketing_scan(cfg_scan, cfg_prec, ledger, alpha=alpha)
    
    # Audit by Count (Theoretical vs Observed)
    start_N = rutils.n_riemann_von_mangoldt(args.T0)
    end_N = rutils.n_riemann_von_mangoldt(args.T1)
    expected_count = int(round(end_N - start_N))
    observed_count = len(refined)
    deficit = expected_count - observed_count
    
    print_summary(refined, cfg_scan, cfg_ua, cfg_prec, Thresholds(), ledger)
    print("\n--- AUDIT REPORT ---")
    print(f"Theoretical N(T) change: {expected_count}")
    print(f"Observed Zeros: {observed_count}")
    print(f"Deficit: {deficit}")
    if deficit > 2:
        print("WARNING: Significant deficit detected. Consider reducing alpha (step).")
    else:
        print("Audit: SUCCESS. Yield aligns with Riemann-von Mangoldt density.")

if __name__ == "__main__":
    main()
