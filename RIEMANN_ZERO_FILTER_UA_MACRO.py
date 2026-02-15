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


# =============================================================================
# SCORE FUNCTIONS: "FILTRAR 0" EN s = 1/2 + iT
# =============================================================================

def zeta_abs(T: float) -> float:
    s = mp.mpf("0.5") + 1j * mp.mpf(T)
    return float(abs(mp.zeta(s)))

def zeta_im(T: float) -> float:
    s = mp.mpf("0.5") + 1j * mp.mpf(T)
    return float(mp.im(mp.zeta(s)))

def score_fast(T: float, prec: PrecisionConfig) -> float:
    mp.mp.dps = prec.dps_low
    return zeta_abs(T)

def score_mid(T: float, prec: PrecisionConfig) -> float:
    mp.mp.dps = prec.dps_mid
    return zeta_abs(T)

def score_full(T: float, prec: PrecisionConfig) -> float:
    mp.mp.dps = prec.dps_high
    return zeta_abs(T)

def hardy_z(T: float, prec: PrecisionConfig) -> float:
    mp.mp.dps = prec.dps_mid
    t = mp.mpf(T)
    theta = mp.siegeltheta(t)
    z = mp.exp(1j * theta) * mp.zeta(0.5 + 1j * t)
    return float(mp.re(z))


# =============================================================================
# TRI-FILTER + ZOOM LOCAL
# =============================================================================

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


def local_zoom_grid(center_T: float, radius: float, points: int) -> np.ndarray:
    points = max(3, int(points))
    if points % 2 == 0:
        points += 1
    return np.linspace(center_T - radius, center_T + radius, points)


def try_bracket_by_im(T: float, step: float, prec: PrecisionConfig, eps: float) -> Optional[Tuple[float, float]]:
    """
    Heurística: si Im(zeta) cambia de signo alrededor, sugiere un intervalo.
    No garantiza un cero (porque Re también importa), pero es un buen "hint".
    """
    mp.mp.dps = prec.dps_mid
    a = T - step
    b = T + step
    ia = zeta_im(a)
    ib = zeta_im(b)
    if abs(ia) < eps or abs(ib) < eps:
        return (a, b)
    if ia == 0.0:
        return (a, a)
    if ib == 0.0:
        return (b, b)
    if ia * ib < 0:
        return (a, b)
    return None


def tri_filter_scan(cfg_scan: ScanConfig, cfg_prec: PrecisionConfig, thr: Thresholds,
                    ledger: RiemannLedger, enable_bracket: bool = True) -> List[Candidate]:
    """
    Pipeline:
    - L0: eval score_fast, gate por tau_fast
    - L1: eval score_mid, gate por tau_mid
    - Mantiene top hits L1 por score_mid (para no reventar B)
    - L2: zoom local + score_mid para elegir mejor punto, luego score_full (verificación)
    """
    candidates: List[Candidate] = []
    hits_L1: List[Candidate] = []

    T_values = np.arange(cfg_scan.T0, cfg_scan.T1 + 1e-12, cfg_scan.step)
    ledger.begin()

    # ---------- FASE A: L0 + L1 ----------
    temp_candidates: List[Candidate] = []
    for T in T_values:
        ua_cost_L0 = 10
        if not ledger.can_spend_A(ua_cost_L0):
            break
        ledger.spend_A(ua_cost_L0)
        ledger.n_L0 += 1
        s0 = score_fast(float(T), cfg_prec)

        if s0 > thr.tau_fast:
            continue
        ledger.n_L0_pass += 1
        
        # Evaluate L1 for all L0 passes to find local minima
        ua_cost_L1 = 35
        if not ledger.can_spend_A(ua_cost_L1):
            break
        ledger.spend_A(ua_cost_L1)
        ledger.n_L1 += 1
        s1 = score_mid(float(T), cfg_prec)
        temp_candidates.append(Candidate(T=float(T), s_fast=float(s0), s_mid=float(s1)))

    # Identify local minima in s_mid
    for i in range(len(temp_candidates)):
        c = temp_candidates[i]
        if c.s_mid > thr.tau_mid:
            continue
        
        # Check neighbors
        is_min = True
        if i > 0 and temp_candidates[i-1].s_mid < c.s_mid:
            is_min = False
        if i < len(temp_candidates) - 1 and temp_candidates[i+1].s_mid < c.s_mid:
            is_min = False
            
        if is_min:
            ledger.n_L1_pass += 1
            hits_L1.append(c)

    if len(hits_L1) > cfg_scan.max_hits_L1:
        hits_L1.sort(key=lambda x: x.s_mid)
        hits_L1 = hits_L1[:cfg_scan.max_hits_L1]

    # ---------- FASE B: ZOOM + L2 ----------
    hits_L1.sort(key=lambda x: x.s_mid)
    hits_L1 = hits_L1[:cfg_scan.max_hits_L2]

    for c in hits_L1:
        ua_cost_zoom_point = 25
        ua_cost_full = 120

        grid = local_zoom_grid(c.T, cfg_scan.zoom_radius, cfg_scan.zoom_points)
        best_T = c.T
        best_s_mid = c.s_mid

        for Tz in grid:
            if not ledger.can_spend_B(ua_cost_zoom_point):
                break
            ledger.spend_B(ua_cost_zoom_point)
            ledger.n_zoom += 1
            sm = score_mid(float(Tz), cfg_prec)
            if sm < best_s_mid:
                best_s_mid = float(sm)
                best_T = float(Tz)

        c.refined_T = best_T
        c.refined_s_mid = best_s_mid

        if enable_bracket:
            ua_cost_bracket = 40
            if ledger.can_spend_B(ua_cost_bracket):
                ledger.spend_B(ua_cost_bracket)
                hint = try_bracket_by_im(best_T, cfg_scan.step, cfg_prec, thr.bracket_im_eps)
                c.bracket_hint = hint

        if not ledger.can_spend_B(ua_cost_full):
            break
        ledger.spend_B(ua_cost_full)
        ledger.n_L2 += 1
        sf = score_full(best_T, cfg_prec)
        c.verified_s_full = float(sf)

        # --- UPGRADE: Confidence Scoring ---
        conf_cfg = RiemannConfidenceConfig()
        scorer = RiemannConfidenceScorer(conf_cfg)
        det = RiemannDetection(
            t_center=best_T,
            bracket=c.bracket_hint if c.bracket_hint else (best_T-0.001, best_T+0.001),
            hs_value=float(sf),
            precision_bits=int(mp.mp.prec)
        )
        c.confidence = scorer.score(det)

        # --- UPGRADE: Hodge Hostility Test ---
        hostile_cfg = HostilityConfig(
            trials=8,
            coeff_jitter=1e-8,    # Jitter muy pequeño para no alejarse del cero
            rational_noise=1e-9   # Ruido mínimo
        )
        def hodge_eval(coeffs: List[float], meta: Dict[str, Any]) -> float:
            tx = coeffs[0]
            mp.mp.dps = cfg_prec.dps_high
            return zeta_abs(tx)

        tester = HostilityTester(hostile_cfg, evaluate_relation=hodge_eval)
        rel = CandidateRelation(coeffs=[best_T], value=float(sf))
        
        ua_cost_hodge = hostile_cfg.trials * 50 
        if ledger.can_spend_B(ua_cost_hodge):
            ledger.spend_B(ua_cost_hodge)
            is_struct, rate = tester.hostile_test(rel, tol=1e-3) # Tolerancia relativa al valor del campo
            c.hs_survival = rate

        # --- UPGRADE: Brent Confirmation ---
        z_func = lambda t: hardy_z(t, cfg_prec)
        confirm = rutils.try_bracket_and_confirm(z_func, c.refined_T, cfg_scan.step / 2.0)
        c.status = confirm.get("status", "VALLEY_ONLY")
        if c.status == "CONFIRMED":
            c.refined_T = confirm.get("t_root")
            c.root_val = confirm.get("f_root")
            c.verified_s_full = abs(c.root_val) if c.root_val is not None else c.verified_s_full

    # --- UPGRADE: Dedupe & Tag Edges ---
    # Convert candidates to dicts for utils
    c_dicts = []
    for c in hits_L1:
        d = asdict(c)
        d["t_center"] = c.refined_T
        d["absZ"] = c.verified_s_full
        c_dicts.append(d)
    
    deduped = rutils.dedupe_candidates(c_dicts, key_t="t_center", eps=0.1)
    rutils.tag_edges(deduped, cfg_scan.T0, cfg_scan.T1, cfg_scan.T1 - cfg_scan.T0) # Use full range for edge tagging if needed

    # Final refined list
    final_candidates = []
    for d in deduped:
        cc = Candidate(**{k: v for k, v in d.items() if k not in ["t_center", "absZ"]})
        final_candidates.append(cc)

    ledger.end()
    final_candidates.sort(key=lambda x: x.verified_s_full if x.verified_s_full is not None else 1e9)
    return final_candidates

def print_summary(refined: List[Candidate], cfg_scan: ScanConfig, cfg_ua: UAConfig,
                  cfg_prec: PrecisionConfig, thr: Thresholds, ledger: RiemannLedger):
    print("\n=== RIEMANN ZERO FILTER | UA MACRO REPORT ===")
    print(f"Scan Range: T in [{cfg_scan.T0}, {cfg_scan.T1}] step={cfg_scan.step}")
    print(f"Zoom: radius={cfg_scan.zoom_radius} points={cfg_scan.zoom_points}")
    print(f"Budgets: total={cfg_ua.budget_total} | A={ledger.A_budget} | B={ledger.B_budget}")
    print(f"Precision dps: low={cfg_prec.dps_low} mid={cfg_prec.dps_mid} high={cfg_prec.dps_high}")
    print(f"Thresholds: tau_fast={thr.tau_fast} tau_mid={thr.tau_mid}")
    print("\n--- Telemetry ---")
    print(f"UA spent: {ledger.spent} (A={ledger.A_spent} | B={ledger.B_spent})")
    kick_pct = 100.0 * (ledger.ua_kick / ledger.spent) if ledger.spent > 0 else 0.0
    print(f"State split: FLOW_UA={ledger.ua_flow} | KICK_UA={ledger.ua_kick} | Kick%={kick_pct:.1f}%")
    print(f"L0: {ledger.n_L0} | L0 pass: {ledger.n_L0_pass}")
    print(f"L1: {ledger.n_L1} | L1 pass: {ledger.n_L1_pass}")
    print(f"Zoom evals: {ledger.n_zoom} | L2 verifies: {ledger.n_L2}")
    print(f"Elapsed: {ledger.elapsed:.2f}s")
    print("\n--- Top Candidates (closest to 0 by |zeta|) ---")
    k = min(200, len(refined))
    for i in range(k):
        c = refined[i]
        hint = f" | {c.status}"
        if c.bracket_hint is not None:
            hint += f" | bracket[{c.bracket_hint[0]:.6f}, {c.bracket_hint[1]:.6f}]"
        if c.edge:
            hint += " | EDGE"
        print(
            f"{i+1:02d}) T0={c.T:.4f} refT={c.refined_T:.8f} "
            f"FULL={c.verified_s_full:.2e} CONF={c.confidence:.2f} "
            f"HS={c.hs_survival:.2f}{hint}"
        )
    if len(refined) == 0:
        print("No candidates passed L2.")

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--T0", type=float, default=1000.0)
    p.add_argument("--T1", type=float, default=1200.0)
    p.add_argument("--step", type=float, default=0.05)
    p.add_argument("--zoom_radius", type=float, default=0.50)
    p.add_argument("--zoom_points", type=int, default=41)
    p.add_argument("--max_hits_L1", type=int, default=200)
    p.add_argument("--max_hits_L2", type=int, default=40)
    p.add_argument("--no_bracket", action="store_true")
    p.add_argument("--budget", type=int, default=500000)
    p.add_argument("--A_frac", type=float, default=0.70)
    p.add_argument("--B_frac", type=float, default=0.30)
    p.add_argument("--dps_low", type=int, default=25)
    p.add_argument("--dps_mid", type=int, default=60)
    p.add_argument("--dps_high", type=int, default=120)
    p.add_argument("--tau_fast", type=float, default=0.5)
    p.add_argument("--tau_mid", type=float, default=0.2)
    p.add_argument("--bracket_im_eps", type=float, default=1e-3)
    return p.parse_args()

def main():
    args = parse_args()
    cfg_scan = ScanConfig(T0=args.T0, T1=args.T1, step=args.step, zoom_radius=args.zoom_radius,
                          zoom_points=args.zoom_points, max_hits_L1=args.max_hits_L1, max_hits_L2=args.max_hits_L2)
    cfg_ua = UAConfig(budget_total=args.budget, A_frac=args.A_frac, B_frac=args.B_frac)
    cfg_prec = PrecisionConfig(dps_low=args.dps_low, dps_mid=args.dps_mid, dps_high=args.dps_high)
    thr = Thresholds(tau_fast=args.tau_fast, tau_mid=args.tau_mid, bracket_im_eps=args.bracket_im_eps)
    ledger = RiemannLedger(cfg_ua)
    refined = tri_filter_scan(cfg_scan, cfg_prec, thr, ledger, enable_bracket=(not args.no_bracket))
    print_summary(refined, cfg_scan, cfg_ua, cfg_prec, thr, ledger)

if __name__ == "__main__":
    main()
