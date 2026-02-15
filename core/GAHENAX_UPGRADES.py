#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GAHENAX_UPGRADES.py
===================
Paquete de mejoras operativas (capas) para:

1) Caja de cambios condicional (Gearbox): cambia estrategia cuando hay estancamiento geométrico.
2) Inserción con memoria corta: evita repetir maniobras en estados casi idénticos (anti-loop).
3) Riemann: score de confianza para detecciones Hardy–Siegel (intensidad de radar).
4) Hodge: prueba de hostilidad (intenta destruir la relación; si sobrevive, es estructura).
5) Gobernanza global: estados RUNNING/STAGNATED/SILENT para logs y decisiones limpias.

Diseño:
- NO depende de tu motor real: expone hooks y protocolos.
- Puedes integrar con antigravity o tu runner actual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple
from collections import deque
import math
import random
import time


# =============================================================================
# 0) Tipos base y utilidades
# =============================================================================

class OpState(Enum):
    RUNNING = "RUNNING"
    STAGNATED = "STAGNATED"
    SILENT = "SILENT"


@dataclass
class StepMetrics:
    """
    Métricas mínimas por paso, suficientes para gobernanza.
    Rellena lo que tengas: norma, "gradiente efectivo", indicadores GS, swaps, etc.
    """
    step: int
    norm: float
    grad_eff: float  # proxy de "pendiente": cuanto cambia algo útil por paso
    geom_flat: float # proxy: 0..1 donde 1 = muy plano / estancado geométricamente
    swaps: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


def safe_float(x: float) -> float:
    if x is None or isinstance(x, bool):
        return float("nan")
    try:
        xf = float(x)
        if math.isfinite(xf):
            return xf
        return float("nan")
    except Exception:
        return float("nan")


def cosine_sim(a: Sequence[float], b: Sequence[float], eps: float = 1e-12) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        x = float(x); y = float(y)
        dot += x * y
        na += x * x
        nb += y * y
    denom = (math.sqrt(na) * math.sqrt(nb)) + eps
    return dot / denom


# =============================================================================
# 1) Caja de cambios condicional (Gearbox)
# =============================================================================

@dataclass
class GearboxConfig:
    stagnation_window: int = 200
    norm_improve_tol: float = 1e-9
    grad_min: float = 1e-6
    geom_flat_min: float = 0.85
    micro_explore_budget_ratio: float = 0.10  # 10% UA
    cooldown_steps: int = 50                  # no cambiar de marcha cada paso


class GearMode(Enum):
    DRILL = "DRILL"          # explotación fuerte
    MICRO_EXPLORE = "MICRO"  # exploración local controlada


@dataclass
class GearboxController:
    cfg: GearboxConfig
    _history: Deque[StepMetrics] = field(default_factory=lambda: deque(maxlen=2000))
    _last_shift_step: int = -10**9

    def push(self, m: StepMetrics) -> None:
        self._history.append(m)

    def should_shift(self) -> Tuple[bool, GearMode, str]:
        """
        Decide si cambiar de marcha:
        - si norma no mejora en ventana
        - y gradiente efectivo es muy bajo
        - y geom_flat indica planicie alta
        """
        if len(self._history) < self.cfg.stagnation_window:
            return (False, GearMode.DRILL, "warming_up")

        last = self._history[-1]
        if (last.step - self._last_shift_step) < self.cfg.cooldown_steps:
            return (False, GearMode.DRILL, "cooldown")

        window = list(self._history)[-self.cfg.stagnation_window:]
        norms = [w.norm for w in window]
        norm_best = min(norms)
        norm_now = norms[-1]
        norm_improved = (norm_now - norm_best) <= self.cfg.norm_improve_tol

        grad_now = window[-1].grad_eff
        geom_now = window[-1].geom_flat

        # Estancamiento: no mejoras + grad bajo + geometría plana
        if norm_improved and grad_now < self.cfg.grad_min and geom_now >= self.cfg.geom_flat_min:
            self._last_shift_step = last.step
            return (True, GearMode.MICRO_EXPLORE, "stagnation_detected")

        return (False, GearMode.DRILL, "ok")


# =============================================================================
# 2) Memoria corta anti-loop (Inserción con memoria)
# =============================================================================

@dataclass
class ShortMemoryConfig:
    max_items: int = 64
    similarity_threshold: float = 0.985  # cos sim alta = casi idéntico
    ban_horizon: int = 10                # cuántos pasos prohibir la misma maniobra


@dataclass
class MemoryItem:
    signature: Tuple[float, ...]               # vector pequeño del estado
    action_id: str                             # maniobra elegida
    step: int


@dataclass
class ShortTermActionMemory:
    cfg: ShortMemoryConfig
    items: Deque[MemoryItem] = field(default_factory=lambda: deque(maxlen=64))
    banned: Dict[str, int] = field(default_factory=dict)  # action_id -> until_step

    def _sig(self, metrics: StepMetrics) -> Tuple[float, ...]:
        """
        Firma compacta. Ajusta a tu mundo.
        Incluye:
        - norma
        - grad_eff
        - geom_flat
        - swaps
        - y algunos extras si existen (p.ej. gs_ratio, mu_energy)
        """
        extra_keys = ("gs_ratio", "mu_energy", "lovasz_margin")
        extra_vals = [safe_float(metrics.extra.get(k, 0.0)) for k in extra_keys]
        return (
            float(metrics.norm),
            float(metrics.grad_eff),
            float(metrics.geom_flat),
            float(metrics.swaps),
            *extra_vals,
        )

    def note(self, metrics: StepMetrics, action_id: str) -> None:
        sig = self._sig(metrics)
        self.items.append(MemoryItem(sig, action_id, metrics.step))
        self.banned[action_id] = metrics.step + self.cfg.ban_horizon

    def is_banned(self, action_id: str, step: int) -> bool:
        until = self.banned.get(action_id, -1)
        return step <= until

    def suggest_action(
        self,
        metrics: StepMetrics,
        candidates: List[str],
        fallback: str
    ) -> str:
        """
        Si estamos en un estado casi idéntico a uno previo y la acción previa está baneada,
        escoge otra. Si todo está baneado, usa fallback.
        """
        step = metrics.step
        cand = [c for c in candidates if not self.is_banned(c, step)]
        if not cand:
            return fallback

        sig_now = self._sig(metrics)
        best_sim = -1.0
        best_item: Optional[MemoryItem] = None

        for it in self.items:
            sim = cosine_sim(sig_now, it.signature)
            if sim > best_sim:
                best_sim = sim
                best_item = it

        # Si el estado es casi idéntico a uno previo, evitamos repetir la misma acción
        if best_item and best_sim >= self.cfg.similarity_threshold:
            # quita la acción previa si está disponible
            filtered = [c for c in cand if c != best_item.action_id]
            if filtered:
                return random.choice(filtered)

        return random.choice(cand)


# =============================================================================
# 3) Riemann: Confidence score (Hardy–Siegel detecciones)
# =============================================================================

@dataclass
class RiemannDetection:
    """
    Representa una detección de cero (o candidato) basada en Hardy–Siegel.
    No asume implementación: solo contiene lo medible.
    """
    t_center: float              # ubicación aproximada
    bracket: Tuple[float, float] # intervalo donde se detecta
    hs_value: float              # valor del sensor (p.ej. Z(t) real)
    precision_bits: int
    repeats: int = 1
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiemannConfidenceConfig:
    w_stability: float = 0.45
    w_width: float = 0.25
    w_repeat: float = 0.30
    # escalas (ajusta a tu realidad)
    width_good: float = 1e-3
    width_bad: float = 1e-1
    precision_good: int = 200
    precision_bad: int = 80


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class RiemannConfidenceScorer:
    cfg: RiemannConfidenceConfig

    def score(self, det: RiemannDetection) -> float:
        """
        Score 0..1 basado en:
        - estabilidad: mejora con precisión alta + variación baja (meta: hs_var)
        - anchura del bracket: más estrecho = mejor
        - repetibilidad: repeats altos = mejor
        """
        a, b = det.bracket
        width = abs(b - a)

        # Width score: good cuando width <= width_good, bad cuando >= width_bad
        if width <= self.cfg.width_good:
            s_width = 1.0
        elif width >= self.cfg.width_bad:
            s_width = 0.0
        else:
            # interpolación inversa
            s_width = 1.0 - (width - self.cfg.width_good) / (self.cfg.width_bad - self.cfg.width_good)

        # Precision score
        if det.precision_bits >= self.cfg.precision_good:
            s_prec = 1.0
        elif det.precision_bits <= self.cfg.precision_bad:
            s_prec = 0.0
        else:
            s_prec = (det.precision_bits - self.cfg.precision_bad) / (self.cfg.precision_good - self.cfg.precision_bad)

        # Stability proxy: usa hs_var si existe
        hs_var = safe_float(det.meta.get("hs_var", 0.0))
        # menor var => mayor estabilidad
        s_var = 1.0 / (1.0 + abs(hs_var))
        s_stability = clamp01(0.6 * s_prec + 0.4 * s_var)

        # Repeat score (satura)
        s_repeat = clamp01(math.log1p(det.repeats) / math.log1p(8.0))  # 8 repeticiones ≈ 1.0

        score = (
            self.cfg.w_stability * s_stability +
            self.cfg.w_width * s_width +
            self.cfg.w_repeat * s_repeat
        )
        return clamp01(score)


# =============================================================================
# 4) Hodge: Prueba de hostilidad (intenta destruir el candidato)
# =============================================================================

@dataclass
class HostilityConfig:
    trials: int = 16
    coeff_jitter: float = 1e-3          # perturbación relativa
    basis_rotation_noise: float = 1e-3  # simula pequeñas rotaciones
    rational_noise: float = 1e-6        # ruido racional controlado
    survive_threshold: float = 0.70     # proporción de trials que debe sobrevivir


@dataclass
class CandidateRelation:
    """
    Representa una relación candidata (p.ej. vector racional/coeficientes).
    """
    coeffs: List[float]
    value: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HostilityTester:
    cfg: HostilityConfig
    # hooks: tú inyectas estas funciones reales
    evaluate_relation: Callable[[List[float], Dict[str, Any]], float] = None

    def _perturb(self, coeffs: List[float]) -> List[float]:
        out = []
        for c in coeffs:
            # jitter relativo
            j = 1.0 + random.uniform(-self.cfg.coeff_jitter, self.cfg.coeff_jitter)
            out.append(c * j)
        return out

    def _add_rational_noise(self, coeffs: List[float]) -> List[float]:
        out = []
        for c in coeffs:
            # ruido racional controlado: n/d pequeño
            num = random.randint(-3, 3)
            den = random.choice([10, 20, 50, 100])
            out.append(c + (num / den) * self.cfg.rational_noise)
        return out

    def hostile_test(self, cand: CandidateRelation, tol: float) -> Tuple[bool, float]:
        """
        Devuelve (sobrevive?, survival_rate).
        Sobrevive si la relación reaparece/permanece dentro de tol en suficientes trials.
        """
        if self.evaluate_relation is None:
            raise ValueError("HostilityTester.evaluate_relation hook is required.")

        survives = 0
        for _ in range(self.cfg.trials):
            coeffs = cand.coeffs[:]
            coeffs = self._perturb(coeffs)
            coeffs = self._add_rational_noise(coeffs)

            # "basis_rotation_noise" se pasa por meta como hint
            meta = dict(cand.meta)
            meta["basis_rotation_noise"] = self.cfg.basis_rotation_noise

            v = float(self.evaluate_relation(coeffs, meta))
            if abs(v - cand.value) <= tol:
                survives += 1

        rate = survives / float(self.cfg.trials)
        return (rate >= self.cfg.survive_threshold, rate)


# =============================================================================
# 5) Gobernanza global: estados de silencio
# =============================================================================

@dataclass
class GovernorConfig:
    silent_on_stagnation: bool = True
    silent_duration_steps: int = 200
    minimal_log: bool = True


@dataclass
class OutputLogger:
    """
    Logger controlado por estado.
    En SILENT solo emite métricas crudas (si minimal_log True).
    """
    def log(self, state: OpState, msg: str, metrics: Optional[StepMetrics] = None) -> None:
        if state == OpState.SILENT:
            if metrics is None:
                return
            # Métricas crudas: sin interpretación
            print(f"[SILENT] step={metrics.step} norm={metrics.norm:.6g} grad={metrics.grad_eff:.3g} geom={metrics.geom_flat:.3g} swaps={metrics.swaps}")
            return
        print(msg)


@dataclass
class GlobalGovernor:
    cfg: GovernorConfig
    state: OpState = OpState.RUNNING
    silent_until_step: int = -1
    logger: OutputLogger = field(default_factory=OutputLogger)

    def update_state(self, step: int, stagnated: bool) -> None:
        if stagnated and self.cfg.silent_on_stagnation:
            self.state = OpState.SILENT
            self.silent_until_step = step + self.cfg.silent_duration_steps
            return

        if self.state == OpState.SILENT and step <= self.silent_until_step:
            return

        # sale del silencio
        if self.state == OpState.SILENT and step > self.silent_until_step:
            self.state = OpState.RUNNING

        if stagnated:
            self.state = OpState.STAGNATED
        else:
            self.state = OpState.RUNNING


# =============================================================================
# 6) Integración: Runner genérico (pluggable)
# =============================================================================

@dataclass
class RunnerHooks:
    """
    Tú conectas estas funciones reales.

    - step_fn: ejecuta UN paso del motor y devuelve nuevos metrics.
    - action_apply_fn: aplica una maniobra (action_id) al motor.
    - get_action_candidates_fn: lista de maniobras posibles.
    """
    step_fn: Callable[[Any], StepMetrics]
    action_apply_fn: Callable[[Any, str], None]
    get_action_candidates_fn: Callable[[Any], List[str]]


@dataclass
class UpgradedRunnerConfig:
    max_steps: int = 5000
    # si el motor entra en MICRO, cuántos pasos dura antes de volver a DRILL
    micro_explore_steps: int = 50
    # tolerancia para hostilidad (si usas Hodge)
    hostility_tol: float = 1e-6


@dataclass
class UpgradedRunner:
    """
    Orquestador:
    - Gearbox decide DRILL vs MICRO
    - Memoria corta evita repetir la misma maniobra en estados similares
    - Gobernanza controla logs (SILENT)
    """
    hooks: RunnerHooks
    gearbox: GearboxController
    memory: ShortTermActionMemory
    governor: GlobalGovernor
    cfg: UpgradedRunnerConfig

    def run(self, engine: Any, seed: Optional[int] = None) -> List[StepMetrics]:
        if seed is not None:
            random.seed(seed)

        metrics_trace: List[StepMetrics] = []
        micro_left = 0

        for _ in range(self.cfg.max_steps):
            m = self.hooks.step_fn(engine)
            metrics_trace.append(m)
            self.gearbox.push(m)

            shift, mode, reason = self.gearbox.should_shift()
            stagnated = (reason == "stagnation_detected")

            self.governor.update_state(m.step, stagnated=stagnated)

            # logging
            self.governor.logger.log(
                self.governor.state,
                msg=f"[{self.governor.state.value}] step={m.step} norm={m.norm:.6g} grad={m.grad_eff:.3g} geom={m.geom_flat:.3g} swaps={m.swaps} shift={shift} mode={mode.value} reason={reason}",
                metrics=m
            )

            if shift and mode == GearMode.MICRO_EXPLORE:
                micro_left = self.cfg.micro_explore_steps

            # Decide acción
            candidates = self.hooks.get_action_candidates_fn(engine)
            fallback = candidates[0] if candidates else "noop"

            if micro_left > 0:
                # MICRO: elegimos acción evitando loops, pero permitimos diversidad
                action = self.memory.suggest_action(m, candidates, fallback=fallback)
                micro_left -= 1
            else:
                # DRILL: acción preferida (primera), pero evita repetir exactamente la misma si está baneada
                preferred = candidates[0] if candidates else "noop"
                if self.memory.is_banned(preferred, m.step):
                    action = self.memory.suggest_action(m, candidates, fallback=fallback)
                else:
                    action = preferred

            # Aplica acción y registra en memoria
            if candidates:
                self.hooks.action_apply_fn(engine, action)
                self.memory.note(m, action_id=action)

        return metrics_trace


# =============================================================================
# 7) Ejemplo mínimo de motor dummy (para que puedas probar el arnés)
# =============================================================================

class DummyEngine:
    """
    Motor de juguete: simula bajar norma con estancamientos.
    Sustituye por tu motor real.
    """
    def __init__(self):
        self.step = 0
        self.norm = 1500.0
        self.phase = 0
        self.swaps = 0

    def step_once(self) -> StepMetrics:
        self.step += 1
        # patrón: baja al principio, luego se estanca, luego baja
        if self.step < 300:
            dn = -random.random() * 1.5
            flat = 0.2
        elif 300 <= self.step < 600:
            dn = -random.random() * 0.02
            flat = 0.92
        else:
            dn = -random.random() * 0.9
            flat = 0.4

        self.norm = max(0.0, self.norm + dn)
        grad = abs(dn)
        self.swaps = (self.swaps + (1 if random.random() < 0.05 else 0))

        return StepMetrics(
            step=self.step,
            norm=self.norm,
            grad_eff=grad,
            geom_flat=flat,
            swaps=self.swaps,
            extra={"gs_ratio": random.random(), "lovasz_margin": random.uniform(-0.1, 0.1)}
        )

    def apply_action(self, action_id: str) -> None:
        # simula que algunas acciones "rompen" estancamiento
        if action_id == "reorder_basis":
            self.norm *= (0.999 + random.random() * 0.001)
        elif action_id == "swap_heavy":
            self.norm *= (0.998 + random.random() * 0.002)
        elif action_id == "metric_tweak":
            self.norm *= (0.9995 + random.random() * 0.0005)
        # no-op implícito


def dummy_step_fn(engine: DummyEngine) -> StepMetrics:
    return engine.step_once()

def dummy_candidates_fn(engine: DummyEngine) -> List[str]:
    # En tu motor real esto dependerá del estado
    return ["swap_heavy", "reorder_basis", "metric_tweak"]

def dummy_apply_action(engine: DummyEngine, action_id: str) -> None:
    engine.apply_action(action_id)


def demo():
    hooks = RunnerHooks(
        step_fn=dummy_step_fn,
        action_apply_fn=dummy_apply_action,
        get_action_candidates_fn=dummy_candidates_fn
    )

    gearbox = GearboxController(GearboxConfig(stagnation_window=120))
    memory = ShortTermActionMemory(ShortMemoryConfig(max_items=64))
    governor = GlobalGovernor(GovernorConfig(silent_on_stagnation=True, silent_duration_steps=120))

    runner = UpgradedRunner(
        hooks=hooks,
        gearbox=gearbox,
        memory=memory,
        governor=governor,
        cfg=UpgradedRunnerConfig(max_steps=900, micro_explore_steps=40)
    )

    eng = DummyEngine()
    trace = runner.run(eng, seed=42)
    print(f"\nDONE. steps={len(trace)} final_norm={trace[-1].norm:.6g}")

if __name__ == "__main__":
    demo()
