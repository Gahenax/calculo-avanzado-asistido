"""
audit_dataset.py  -- Gahenax Full Dataset Audit
Loads all ledger shards, deduplicates, and computes complete statistics.
"""
import json
import os
import math
import sys
import numpy as np
from scipy import stats as sp_stats

LEDGER_PATH = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis\ledger_riemann_phase1"
FULL_JSONL  = r"c:\Users\USUARIO\OneDrive\Desktop\Tesis\results\riemann\jules_phase1_full.jsonl"

# ── Loader ──────────────────────────────────────────────────────────────────

def load_from_jsonl(path):
    zeros = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                # Try flat t_est
                t = rec.get("t_est")
                # Try nested payload
                if t is None:
                    p = rec.get("payload", {})
                    t = p.get("t_est") or p.get("T") or p.get("refined_T")
                if t and isinstance(t, (int, float)) and t > 0:
                    zeros.append(float(t))
    except FileNotFoundError:
        pass
    return zeros


def load_ledger(ledger_dir):
    all_zeros = []
    shard_report = []
    for fn in sorted(os.listdir(ledger_dir)):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(ledger_dir, fn)
        zs = load_from_jsonl(path)
        t0 = min(zs) if zs else 0
        t1 = max(zs) if zs else 0
        shard_report.append((fn, len(zs), t0, t1))
        all_zeros.extend(zs)
    return sorted(set(all_zeros)), shard_report


# ── Unfolding ────────────────────────────────────────────────────────────────

def riemann_N(t):
    """Smooth Riemann zero counting function N(T) ~ (T/2pi)*log(T/2pi) - T/2pi"""
    if t <= 0:
        return 0.0
    return (t / (2 * math.pi)) * math.log(t / (2 * math.pi)) - t / (2 * math.pi)


def unfold(zeros):
    return np.array([riemann_N(t) for t in zeros])


# ── Main audit ───────────────────────────────────────────────────────────────

def audit(zeros, label):
    zeros = np.array(sorted(zeros))
    n = len(zeros)

    print(f"\n{'='*62}")
    print(f"  GAHENAX FULL AUDIT — {label}")
    print(f"{'='*62}")
    print(f"  Total zeros (unique): {n}")
    print(f"  T range:              [{zeros[0]:.4f}, {zeros[-1]:.4f}]")
    print(f"  Interval width:       {zeros[-1]-zeros[0]:.2f}")

    if n < 50:
        print("  [!] Insufficient sample for robust statistics.")
        return

    # ── 1. Gaps en T-natural ─────────────────────────────────────────────────
    gaps_raw = np.diff(zeros)
    print(f"\n  [1] GAPS NATURALES (en unidades de T)")
    print(f"  Gap medio:  {gaps_raw.mean():.4f}")
    print(f"  Gap min:    {gaps_raw.min():.4f}")
    print(f"  Gap max:    {gaps_raw.max():.4f}")
    print(f"  Gap std:    {gaps_raw.std():.4f}")

    # ── 2. Unfolding y gaps normalizados ──────────────────────────────────────
    unf = unfold(zeros)
    gaps = np.diff(unf)
    mean_gap = gaps.mean()
    gaps_norm = gaps / mean_gap

    print(f"\n  [2] GAPS NORMALIZADOS (unfolded, media=1)")
    print(f"  Mean gap unfolded:  {mean_gap:.5f}")
    print(f"  <s>:                {gaps_norm.mean():.4f}  (debe ser 1.0)")
    print(f"  Std(s):             {gaps_norm.std():.4f}  (GUE: ~0.52)")

    # ── 3. r-statistic ───────────────────────────────────────────────────────
    r_vals = np.array([min(gaps_norm[i], gaps_norm[i+1]) /
                       max(gaps_norm[i], gaps_norm[i+1])
                       for i in range(len(gaps_norm)-1)])
    mean_r = r_vals.mean()
    gue_r  = 0.5996
    poisson_r = 0.3863

    print(f"\n  [3] r-STATISTIC (orden local)")
    print(f"  Observado <r>:  {mean_r:.5f}")
    print(f"  GUE esperado:   {gue_r:.5f}  (caos cuantico)")
    print(f"  Poisson:        {poisson_r:.5f}  (sin correlacion)")
    print(f"  Desviacion GUE: {abs(mean_r - gue_r):.5f}")
    if mean_r > gue_r:
        print(f"  INTERPRETACION: Rigidez SUPERIOR a GUE — posible hiper-orden")
    else:
        print(f"  INTERPRETACION: Dentro del regimen GUE")

    # ── 4. ACF lag-1 de gaps ─────────────────────────────────────────────────
    acf1 = np.corrcoef(gaps_norm[:-1], gaps_norm[1:])[0, 1]
    print(f"\n  [4] CORRELACION DE GAPS (ACF lag-1)")
    print(f"  ACF lag-1: {acf1:.4f}  (GUE esperado: ~-0.25)")
    if acf1 < -0.35:
        print(f"  VERDICT: SUPER-RIGIDO — hiperuniformidad espectral detectada")
    elif acf1 < -0.15:
        print(f"  VERDICT: GUE estandar")
    else:
        print(f"  VERDICT: Rigidez debil — posible ruido o espectro degradado")

    # ── 5. FFT de residuos ────────────────────────────────────────────────────
    unf_norm = (unf - unf[0]) / mean_gap
    residues = unf_norm - np.arange(n)
    fft_vals = np.abs(np.fft.rfft(residues - residues.mean()))
    freqs    = np.fft.rfftfreq(n)
    peak_idx = np.argmax(fft_vals[1:]) + 1
    peak_f   = freqs[peak_idx]
    peak_P   = fft_vals[peak_idx]
    # periodo correspondiente
    periodo  = round(1.0 / peak_f) if peak_f > 0 else 0

    print(f"\n  [5] RESONANCIA ESPECTRAL (FFT de residuos)")
    print(f"  Frecuencia pico: {peak_f:.5f} ciclos/cero")
    print(f"  Potencia pico:   {peak_P:.2f}")
    print(f"  Periodo:         ~{periodo} ceros por ciclo")
    if peak_P > 15:
        print(f"  VERDICT: ECO ESPECTRAL fuerte — periodicidad real en la densidad")
    else:
        print(f"  VERDICT: Sin eco significativo")

    # ── 6. Varianza numerica ─────────────────────────────────────────────────
    print(f"\n  [6] VARIANZA NUMERICA Sigma^2(L)")
    print(f"  {'L':>5}  {'Obs':>10}  {'GUE':>10}  {'Ratio':>8}  {'Veredicto'}")
    print(f"  {'-'*55}")
    for L in [1.0, 2.0, 5.0, 10.0]:
        offs   = np.linspace(unf_norm[5], unf_norm[-5] - L, 300)
        counts = [np.searchsorted(unf_norm, o+L) - np.searchsorted(unf_norm, o)
                  for o in offs]
        obs  = float(np.var(counts))
        gue  = (1/math.pi**2) * (math.log(2*math.pi*L) + 1 + 0.5772)
        ratio = obs / gue if gue > 0 else 0
        flag = "<< RIGIDO" if ratio < 0.6 else ("OK" if ratio < 1.1 else ">> DIFUSO")
        print(f"  {L:>5.1f}  {obs:>10.4f}  {gue:>10.4f}  {ratio:>7.1%}  {flag}")

    # ── 7. Veredicto global ───────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  VEREDICTO GLOBAL")
    print(f"{'='*62}")
    clues = []
    if mean_r > gue_r + 0.01:
        clues.append("r-stat SOBRE GUE (+rigidez extra)")
    if acf1 < -0.35:
        clues.append("ACF lag-1 < -0.35 (hiperuniformidad)")
    if peak_P > 15:
        clues.append(f"Eco espectral f={peak_f:.3f} (P={peak_P:.1f})")

    if len(clues) >= 2:
        print(f"  STATUS: [SPECTRAL ANOMALY DETECTED]")
        for c in clues:
            print(f"    - {c}")
        print(f"\n  HYPOTHESIS: Spectrum at T=[{zeros[0]:.0f},{zeros[-1]:.0f}]")
        print(f"  shows rigidity ABOVE GUE with periodic echo at ~{periodo} zeros.")
        print(f"  Consistent with influence of small primes (p=2,3,5)")
        print(f"  resonating in xi at this T level.")
    elif len(clues) == 1:
        print(f"  STATUS: [COMPATIBLE WITH GUE -- weak anomaly]")
        print(f"    Note: {clues[0]}")
    else:
        print(f"  STATUS: [GREEN] Standard GUE behaviour")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    print("Loading data...")
    zeros_full = load_from_jsonl(FULL_JSONL)
    print(f"  jules_phase1_full.jsonl: {len(zeros_full)} zeros")

    # Carga desde ledger de shards
    zeros_shard, shard_report = load_ledger(LEDGER_PATH)
    print(f"  ledger_riemann_phase1/:  {len(zeros_shard)} ceros")

    print("\n  Shards por archivo:")
    for fn, cnt, t0, t1 in shard_report:
        t0s = f"{t0:.2f}" if t0 else "?"
        t1s = f"{t1:.2f}" if t1 else "?"
        print(f"    {fn:40s}  {cnt:4d} ceros  T=[{t0s},{t1s}]")

    # Combina y deduplica
    all_zeros = sorted(set(zeros_full + zeros_shard))
    print(f"\n  TOTAL COMBINADO (unicos): {len(all_zeros)} ceros")

    # Audita conjunto completo
    audit(all_zeros, "DATASET COMPLETO — Phase 1")

    # Audita solo el full jsonl (referencia)
    if zeros_full:
        audit(zeros_full, "jules_phase1_full.jsonl")
