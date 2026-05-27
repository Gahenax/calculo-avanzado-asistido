"""
GAHENAX Phase-2 Probe Recalibration (S, C, H) + Prime-Resonance Decomposition
-----------------------------------------------------------------------------

This module translates the "recalibrate probes" protocol into a concrete,
pluggable Python implementation.

Core idea:
- Build a stable signal x(n) from normalized gaps (after unfolding).
- Decompose x(n) into:
    x(n) ≈ Σ_{p<=Pmax} A_p cos(2π f_p n + φ_p) + residual r(n)
  where f_p = log(p)/(2π)
- Report:
    S(P): arith-energy fraction explained by primes
    C: chaos-residual score (simple composite)
    H: hyperuniformity slope from Σ²(L) across multiple L

Includes "gates" for anti-self-deception:
- Gate1: density sanity (placeholder hook)
- Gate2: minimum arithmetic detection (A_p strength for small primes)
- Gate3: stability across windows
- Gate4: residual still has strong prime lines (detectable leakage)
- Gate5: Σ²(L) stability + slope

You can feed this with:
- zeros_t: list/np.array of imaginary parts of zeta zeros within one shard
- and optionally expected density metrics if you have them

No external deps beyond numpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import math
import numpy as np


# -----------------------------
# Config
# -----------------------------

@dataclass(frozen=True)
class Phase2Config:
    # Prime resonance
    primes: Tuple[int, ...] = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31)
    pmax: int = 31

    # Windowing over zero index n
    window_size: int = 512
    window_step: int = 256

    # Σ²(L) evaluation scales (in units of mean spacing)
    sigma2_L: Tuple[int, ...] = (5, 10, 20, 40)

    # Gates (tune as needed)
    gate2_min_amp: float = 0.02     # minimum amplitude (normalized units) for p in small set
    gate2_small_primes: Tuple[int, ...] = (2, 3, 5, 7, 11)

    gate3_cv_max: float = 0.60      # coefficient of variation upper bound for A_p across windows
    gate4_leak_ratio_max: float = 0.35  # residual prime-energy / raw prime-energy threshold

    # "Chaos residual" composite weights
    c_weight_r: float = 0.55
    c_weight_acf1: float = 0.45

    # ACF target (GUE-like) reference; residual should not be "over-structured"
    gue_acf1_ref: float = -0.25
    gue_r_ref: float = 0.5996


# -----------------------------
# Helpers: primes, frequencies
# -----------------------------

def _filter_primes_upto(primes: Tuple[int, ...], pmax: int) -> List[int]:
    return [p for p in primes if p <= pmax]


def prime_freq(p: int) -> float:
    # f_p = log(p) / (2π)
    return math.log(p) / (2.0 * math.pi)


# -----------------------------
# Unfolding + signal construction
# -----------------------------

def normalize_gaps_from_zeros(zeros_t: np.ndarray) -> np.ndarray:
    """
    Basic unfolding proxy: normalize spacings by mean spacing inside shard.
    Replace this with your canonical unfolding if you have it.
    """
    t = np.asarray(zeros_t, dtype=float)
    if t.ndim != 1 or t.size < 4:
        raise ValueError("Need a 1D array of >=4 zeros.")
    dt = np.diff(t)
    mean_dt = float(np.mean(dt))
    if mean_dt <= 0:
        raise ValueError("Mean spacing must be positive.")
    s = dt / mean_dt
    # Center it to build a stable x(n) for resonance
    return s - float(np.mean(s))


def build_signal_x(zeros_t: np.ndarray) -> np.ndarray:
    """
    x(n) signal used for resonance decomposition.
    Default: centered normalized gaps.
    """
    return normalize_gaps_from_zeros(zeros_t)


# -----------------------------
# Resonance fit (fixed frequencies)
# -----------------------------

def fit_prime_resonance_fixed_freq(
    x: np.ndarray,
    primes: List[int],
) -> Tuple[Dict[int, float], Dict[int, float], np.ndarray]:
    """
    Fit x(n) using fixed basis {cos(2π f_p n), sin(2π f_p n)}.

    Returns:
      A_p: amplitude per prime
      phi_p: phase per prime (in radians)
      residual r(n)
    """
    x = np.asarray(x, dtype=float)
    n = np.arange(x.size, dtype=float)

    # Design matrix: [cos(2π f_p n), sin(2π f_p n)] for each p
    cols = []
    for p in primes:
        f = prime_freq(p)
        ang = 2.0 * math.pi * f * n
        cols.append(np.cos(ang))
        cols.append(np.sin(ang))

    X = np.stack(cols, axis=1)  # shape (N, 2*len(primes))

    # Least squares
    beta, *_ = np.linalg.lstsq(X, x, rcond=None)
    x_hat = X @ beta
    residual = x - x_hat

    A_p: Dict[int, float] = {}
    phi_p: Dict[int, float] = {}
    for i, p in enumerate(primes):
        a = beta[2 * i]      # cos coeff
        b = beta[2 * i + 1]  # sin coeff
        amp = float(np.hypot(a, b))
        # x ≈ a cos + b sin = A cos(θ - φ) with φ = atan2(b, a)
        phi = float(np.arctan2(b, a))
        A_p[p] = amp
        phi_p[p] = phi

    return A_p, phi_p, residual


def windowed_resonance(
    x: np.ndarray,
    cfg: Phase2Config,
) -> Dict[str, Any]:
    """
    Run resonance fit over sliding windows of x(n).
    """
    primes = _filter_primes_upto(cfg.primes, cfg.pmax)
    N = x.size
    if N < cfg.window_size + 2:
        raise ValueError("Signal too short for requested window_size.")

    win_results = []
    for start in range(0, N - cfg.window_size + 1, cfg.window_step):
        end = start + cfg.window_size
        xw = x[start:end]
        A_p, phi_p, r = fit_prime_resonance_fixed_freq(xw, primes)
        win_results.append(
            {"start": start, "end": end, "A_p": A_p, "phi_p": phi_p, "residual": r}
        )

    return {"primes": primes, "windows": win_results}


# -----------------------------
# Metrics: S(P), C, H
# -----------------------------

def arith_energy_fraction(x: np.ndarray, residual: np.ndarray) -> float:
    """
    S(P) = explained_energy / total_energy = 1 - residual_energy/total_energy
    """
    x = np.asarray(x, dtype=float)
    r = np.asarray(residual, dtype=float)
    denom = float(np.sum(x * x))
    if denom <= 1e-18:
        return 0.0
    return float(1.0 - (np.sum(r * r) / denom))


def r_statistic_from_spacings(spacings: np.ndarray) -> float:
    """
    r-statistic based on consecutive spacing ratios:
      r_n = min(s_n, s_{n-1}) / max(s_n, s_{n-1})
    spacings should be positive.
    """
    s = np.asarray(spacings, dtype=float)
    s = s[s > 0]
    if s.size < 3:
        return float("nan")
    a = s[1:]
    b = s[:-1]
    r = np.minimum(a, b) / np.maximum(a, b)
    return float(np.mean(r))


def acf_lag1(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    if x.size < 3:
        return float("nan")
    x0 = x[:-1] - float(np.mean(x[:-1]))
    x1 = x[1:] - float(np.mean(x[1:]))
    denom = float(np.sqrt(np.sum(x0 * x0) * np.sum(x1 * x1)))
    if denom <= 1e-18:
        return 0.0
    return float(np.sum(x0 * x1) / denom)


def sigma2_number_variance(spacings_norm: np.ndarray, L: int,
                           n_origins: int = 400, seed: int = 0) -> float:
    """
    Robust Sigma^2(L) estimator via random interval origins.

    Uses n_origins random start points in [0, total-L] so that the
    sampled counts are approximately independent (no level reuse as origin).
    Border effects are avoided: only origins where origin+L fits are used.

    spacings_norm: positive spacings with mean ~1 (unfolded units)
    L: interval length in unfolded units
    """
    s = np.asarray(spacings_norm, dtype=float)
    s = s[np.isfinite(s) & (s > 0)]
    if s.size < 30:
        return float("nan")

    pos = np.concatenate([[0.0], np.cumsum(s)])
    total = pos[-1]
    if total <= L + 1e-12:
        return float("nan")  # L too large relative to sample

    rng = np.random.default_rng(seed)
    origins = rng.uniform(0.0, total - L, size=n_origins)

    counts = []
    for t in origins:
        left  = np.searchsorted(pos, t,     side="right")
        right = np.searchsorted(pos, t + L, side="right")
        counts.append(max(0, right - left))

    counts = np.asarray(counts, dtype=float)
    return float(np.var(counts, ddof=1))


def effective_alpha(sigma2_by_L: Dict[int, float]) -> float:
    """
    Fit Sigma^2(L) ~ L^alpha on the provided L-set (log-log linear fit).

    Returns alpha (the raw power-law exponent).
    Interpretation:
      Poisson:       alpha ~ 1.0  (linear growth)
      GUE:           alpha ~ 0.0  (log growth  -> appears near-flat in log-log)
      Hyperuniform:  alpha < 0    (Sigma^2 shrinks with L -- rare/artifact)

    NOTE: GUE has log growth, not power-law, so this fit is only an
    approximate local descriptor. Use with confidence intervals when
    claiming physics.
    """
    items = [(L, v) for L, v in sigma2_by_L.items() if np.isfinite(v) and v > 1e-12]
    if len(items) < 2:
        return float("nan")
    Ls = np.array([float(L) for L, _ in items], dtype=float)
    Vs = np.array([float(v) for _, v in items], dtype=float)
    x = np.log(Ls)
    y = np.log(Vs)
    alpha = float(np.polyfit(x, y, 1)[0])
    return alpha  # NOT negated — caller interprets directly


def chaos_residual_score(
    r_stat: float,
    acf1_val: float,
    cfg: Phase2Config,
) -> float:
    """
    Bounded score in [0,1]: how close residual looks to GUE.
    1.0 = perfectly GUE-like residual (arithmetic fully extracted).
    0.0 = residual still highly structured.
    """
    if not np.isfinite(r_stat) or not np.isfinite(acf1_val):
        return 0.0

    dr = abs(r_stat - cfg.gue_r_ref)
    da = abs(acf1_val - cfg.gue_acf1_ref)

    r_term = math.exp(-dr / 0.03)
    a_term = math.exp(-da / 0.12)

    score = cfg.c_weight_r * r_term + cfg.c_weight_acf1 * a_term
    return float(max(0.0, min(1.0, score)))


# -----------------------------
# Gates
# -----------------------------

def gate2_min_arith_detection(
    A_p: Dict[int, float],
    cfg: Phase2Config,
    residual: Optional[np.ndarray] = None,
) -> Tuple[bool, str]:
    """
    Gate2 via SNR: A_p / std(residual) > gate2_z_min for all small primes.
    Falls back to absolute threshold only if residual is unavailable.
    """
    small = [p for p in cfg.gate2_small_primes if p in A_p]
    if not small:
        return False, "Gate2: no small primes in A_p."

    if residual is not None:
        sig = float(np.std(residual))
        if sig > 1e-12:
            # SNR-based check (scale-invariant)
            z_min = getattr(cfg, "gate2_z_min", 2.0)
            weak = [p for p in small if (A_p[p] / sig) < z_min]
            if weak:
                snrs = {p: round(A_p[p]/sig, 3) for p in small}
                return False, f"Gate2(SNR): weak for primes {weak}. SNRs={snrs} (z_min={z_min})"
            snrs = {p: round(A_p[p]/sig, 3) for p in small}
            return True, f"Gate2(SNR): pass. SNRs={snrs}"

    # Fallback: absolute threshold (scale-dependent, for small shards)
    weak = [p for p in small if A_p[p] < cfg.gate2_min_amp]
    if weak:
        return False, f"Gate2(abs): weak for primes {weak} (min={cfg.gate2_min_amp})."
    return True, "Gate2(abs): pass."


def gate3_stability_across_windows(
    window_As: List[Dict[int, float]],
    cfg: Phase2Config,
) -> Tuple[bool, str]:
    primes = _filter_primes_upto(cfg.primes, cfg.pmax)
    cvs = []
    for p in primes:
        vals = [w.get(p, 0.0) for w in window_As]
        vals = np.asarray(vals, dtype=float)
        mu = float(np.mean(vals))
        sd = float(np.std(vals))
        if mu <= 1e-12:
            continue
        cvs.append(sd / mu)
    if not cvs:
        return False, "Gate3: insufficient window amplitudes to assess stability."
    cv_med = float(np.median(cvs))
    if cv_med > cfg.gate3_cv_max:
        return False, f"Gate3: instability detected (median CV={cv_med:.3f} > {cfg.gate3_cv_max})."
    return True, f"Gate3: pass (median CV={cv_med:.3f})."


def gate4_residual_leakage(
    x_window: np.ndarray,
    r_window: np.ndarray,
    cfg: Phase2Config,
) -> Tuple[bool, str]:
    primes = _filter_primes_upto(cfg.primes, cfg.pmax)
    _, _, r_raw = fit_prime_resonance_fixed_freq(x_window, primes)
    S_raw = arith_energy_fraction(x_window, r_raw)

    _, _, r_res = fit_prime_resonance_fixed_freq(r_window, primes)
    S_res = arith_energy_fraction(r_window, r_res)

    if S_raw <= 1e-12:
        return False, "Gate4: raw arith energy too small to compute leakage ratio."
    ratio = S_res / S_raw
    if ratio > cfg.gate4_leak_ratio_max:
        return False, f"Gate4: residual still contains strong prime lines (leak ratio={ratio:.3f})."
    return True, f"Gate4: pass (leak ratio={ratio:.3f})."


# -----------------------------
# Main: probe run on one shard
# -----------------------------

@dataclass
class ProbeShardResult:
    zeros_t: np.ndarray
    x: np.ndarray
    spacings_norm: np.ndarray
    primes: List[int]
    A_p_global: Dict[int, float]
    phi_p_global: Dict[int, float]
    residual_global: np.ndarray
    window_summaries: List[Dict[str, Any]] = field(default_factory=list)
    S: float = float("nan")
    C: float = float("nan")
    H: float = float("nan")
    sigma2_by_L: Dict[int, float] = field(default_factory=dict)
    r_stat_residual: float = float("nan")
    acf1_residual: float = float("nan")
    gates: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def run_probe_on_shard(
    zeros_t: np.ndarray,
    cfg: Phase2Config = Phase2Config(),
) -> ProbeShardResult:
    """
    Execute the Phase-2 recalibrated probe logic on one shard worth of zeros.
    """
    zeros_t = np.asarray(zeros_t, dtype=float)
    zeros_t = zeros_t[np.isfinite(zeros_t)]
    zeros_t.sort()
    if zeros_t.size < cfg.window_size + 4:
        raise ValueError(
            f"Not enough zeros in shard ({zeros_t.size}) for window_size={cfg.window_size}."
        )

    spacings = np.diff(zeros_t)
    mean_dt = float(np.mean(spacings))
    spacings_norm = spacings / mean_dt
    x = spacings_norm - float(np.mean(spacings_norm))

    primes = _filter_primes_upto(cfg.primes, cfg.pmax)
    A_p_g, phi_p_g, residual_g = fit_prime_resonance_fixed_freq(x, primes)
    S_val = arith_energy_fraction(x, residual_g)

    r_stat = r_statistic_from_spacings(np.abs(residual_g) + 1e-12)
    acf1 = acf_lag1(residual_g)
    C_val = chaos_residual_score(r_stat, acf1, cfg)

    sigma2_by_L = {L: sigma2_number_variance(spacings_norm, L,
                                            n_origins=400, seed=42)
                  for L in cfg.sigma2_L}
    H_val = effective_alpha(sigma2_by_L)  # alpha exponent, NOT negated

    win = windowed_resonance(x, cfg)
    window_summaries = []
    window_As = []
    gate4_checks = []
    for w in win["windows"]:
        A_p = w["A_p"]
        window_As.append(A_p)
        window_summaries.append({
            "start": w["start"], "end": w["end"], "A_p": A_p, "phi_p": w["phi_p"],
            "S_window": arith_energy_fraction(x[w["start"]:w["end"]], w["residual"]),
        })
        ok4, msg4 = gate4_residual_leakage(x[w["start"]:w["end"]], w["residual"], cfg)
        gate4_checks.append((ok4, msg4))

    gates: Dict[str, Dict[str, Any]] = {}
    ok2, msg2 = gate2_min_arith_detection(A_p_g, cfg, residual=residual_g)
    gates["Gate2"] = {"ok": ok2, "msg": msg2}
    ok3, msg3 = gate3_stability_across_windows(window_As, cfg)
    gates["Gate3"] = {"ok": ok3, "msg": msg3}
    if gate4_checks:
        fails = sum(1 for ok, _ in gate4_checks if not ok)
        ok4a = fails <= max(1, len(gate4_checks) // 5)
        gates["Gate4"] = {
            "ok": ok4a,
            "msg": f"Gate4: {'pass' if ok4a else 'fail'} (failed_windows={fails}/{len(gate4_checks)}).",
            "details": gate4_checks[:5],
        }
    else:
        gates["Gate4"] = {"ok": False, "msg": "Gate4: no windows to evaluate."}
    ok5 = all(np.isfinite(v) for v in sigma2_by_L.values()) and np.isfinite(H_val)
    gates["Gate5"] = {"ok": ok5, "msg": f"Gate5: {'pass' if ok5 else 'fail'} (alpha={H_val:.4f})."}

    return ProbeShardResult(
        zeros_t=zeros_t, x=x, spacings_norm=spacings_norm, primes=primes,
        A_p_global=A_p_g, phi_p_global=phi_p_g, residual_global=residual_g,
        window_summaries=window_summaries, S=S_val, C=C_val, H=H_val,
        sigma2_by_L=sigma2_by_L, r_stat_residual=r_stat, acf1_residual=acf1,
        gates=gates,
    )


def run_fleet(
    shards: Dict[str, np.ndarray],
    cfg: Phase2Config = Phase2Config(),
) -> Dict[str, ProbeShardResult]:
    out: Dict[str, ProbeShardResult] = {}
    for name, zeros in shards.items():
        out[name] = run_probe_on_shard(zeros, cfg)
    return out


# -----------------------------
# CLI: run directly on Phase-1 data
# -----------------------------
if __name__ == "__main__":
    import json
    import os
    import sys

    FULL_JSONL = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis\results\riemann\jules_phase1_full.jsonl"
    LEDGER     = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis\ledger_riemann_phase1"

    def _load_jsonl(path):
        zeros = []
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                t = rec.get("t_est")
                if t is None:
                    p = rec.get("payload", {})
                    t = p.get("t_est") or p.get("T") or p.get("refined_T")
                if t and isinstance(t, (int, float)) and t > 0:
                    zeros.append(float(t))
        return np.array(sorted(set(zeros)))

    # Load full dataset
    zeros_full = _load_jsonl(FULL_JSONL)
    print(f"Loaded {len(zeros_full)} zeros from {FULL_JSONL}")

    # Load per-shard (for per-probe fleet run)
    shard_files = sorted(
        fn for fn in os.listdir(LEDGER) if fn.endswith(".jsonl")
    )
    shards = {}
    for fn in shard_files:
        z = _load_jsonl(os.path.join(LEDGER, fn))
        name = fn.replace("shard_", "").replace(".jsonl", "")
        if len(z) >= 10:
            shards[name] = z

    # -- Global run (all 332 zeros) --
    # window_size must be <= N-4; with 331 gaps use 256
    cfg_global = Phase2Config(
        pmax=31,
        window_size=min(256, len(zeros_full) - 5),
        window_step=128,
        sigma2_L=(5, 10, 20),   # 40 needs more zeros
    )

    print("\n" + "="*60)
    print("  PHASE-2 PROBE — GLOBAL (332 zeros)")
    print("="*60)
    try:
        res = run_probe_on_shard(zeros_full, cfg_global)
        print(f"  S(P)  = {res.S:.6f}   [arith energy fraction explained by primes]")
        print(f"  C     = {res.C:.6f}   [chaos-residual score, 1.0=GUE-like]")
        print(f"  alpha = {res.H:.6f}   [power-law exponent Sigma^2~L^alpha]")
        print(f"                         Poisson:alpha~1 | GUE:alpha~0 | Rigid:alpha<0")

        # Robust Sigma^2 + regime check
        spacings_norm = np.diff(res.zeros_t) / np.mean(np.diff(res.zeros_t))
        pos_total = float(np.sum(spacings_norm))
        print(f"\n  Sigma^2(L) [robust, random origins]:  total_unfolded={pos_total:.1f}")
        print(f"  {'L':>5}  {'obs':>9}  {'GUE':>9}  {'ratio':>8}  {'L/total':>8}  {'regime'}")
        print(f"  {'-'*60}")
        for L, v in res.sigma2_by_L.items():
            gue = (1/math.pi**2) * (math.log(2*math.pi*L) + 1 + 0.5772)
            regime = "OK" if L < pos_total * 0.3 else "!! L>30% of total -- unreliable"
            ratio_str = f"{v/gue:.1%}" if gue > 0 else "N/A"
            print(f"  {L:>5}  {v:>9.4f}  {gue:>9.4f}  {ratio_str:>8}  {L/pos_total:>8.2%}  {regime}")
        print(f"\n  Top amplitudes A_p (global fit):")
        for p in sorted(res.A_p_global.keys()):
            print(f"    p={p:>2d}  A={res.A_p_global[p]:.6f}  phi={res.phi_p_global[p]:+.3f}")
        print(f"\n  Gates:")
        all_ok = True
        for k, v in res.gates.items():
            icon = "[OK]" if v["ok"] else "[!!]"
            print(f"    {icon} {k}: {v['msg']}")
            if not v["ok"]:
                all_ok = False
        print(f"\n  OVERALL: {'ALL GATES PASS' if all_ok else 'SOME GATES FAILED'}")

        # Window stability summary
        if res.window_summaries:
            S_windows = [w["S_window"] for w in res.window_summaries]
            print(f"\n  Window S(P): mean={np.mean(S_windows):.4f}  std={np.std(S_windows):.4f}  "
                  f"min={np.min(S_windows):.4f}  max={np.max(S_windows):.4f}")

    except ValueError as e:
        print(f"  [SKIP] {e}")

    # -- Per-shard fleet run --
    print("\n" + "="*60)
    print("  PHASE-2 FLEET — PER SHARD")
    print("="*60)
    cfg_shard = Phase2Config(
        pmax=31,
        window_size=40,    # small: each shard has ~55 zeros -> 54 gaps
        window_step=20,
        sigma2_L=(5, 10),
    )
    print(f"\n  {'SHARD':<30} {'N':>5} {'S(P)':>8} {'C':>8} {'H':>8} {'Gates'}")
    print(f"  {'-'*70}")
    for name, zeros in sorted(shards.items()):
        try:
            r = run_probe_on_shard(zeros, cfg_shard)
            gates_str = "".join(
                ("." if v["ok"] else "X") for v in r.gates.values()
            )
            print(f"  {name:<30} {len(zeros):>5} {r.S:>8.4f} {r.C:>8.4f} {r.H:>8.4f}  [{gates_str}]")
        except ValueError as e:
            print(f"  {name:<30} {len(zeros):>5} {'--':>8} -- -- [{e}]")
