#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PROMPT_UNICO_LMFDB_RIEMANN_PIPELINE.py
=====================================
Adquisición y Validación de Ceros de Riemann (LMFDB).

CARACTERÍSTICAS AVANZADAS:
- Backoff exponencial en red.
- Detección activa de bloqueos (JS/Captcha).
- Extracción de región de tabla (reduce ruido).
- Filtro monotónico estricto (sin reordenamiento).
- VALIDACIÓN DE DENSIDAD ESPECTRAL: compara cantidad observada de ceros
  en [T0, T1] con predicción aproximada N(T) de Riemann–von Mangoldt.
  Si observed/expected sale fuera de tolerancia, aborta (strict=True).

USO:
  python PROMPT_UNICO_LMFDB_RIEMANN_PIPELINE.py --k 100000 --page 100 --sleep 0.5 --strict
"""

import argparse
import hashlib
import json
import math
import re
import time
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------------- CONFIG ----------------
BASE_PUBLIC = "https://www.lmfdb.org/zeros/zeta/"
DATA_DIR = Path("data")
ZEROS_FILE = DATA_DIR / "zeros_lmfdb_gamma.txt"
META_FILE = DATA_DIR / "meta.json"

# ---------------- META ----------------
@dataclass
class Meta:
    source: str
    fetched_at_utc: str
    requested_k: int
    acquired_k: int
    page_size: int
    pages_fetched: int
    sleep_seconds: float
    output_file: str
    output_sha256: str = ""
    first_gamma: Optional[float] = None
    last_gamma: Optional[float] = None
    max_gap: Optional[float] = None
    density_ratio_observed_expected: Optional[float] = None

# ---------------- UTILS & MATH ----------------
def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _N_von_mangoldt(T: float) -> float:
    """
    Aproximación:
      N(T) ≈ (T/(2π)) log(T/(2π)) - (T/(2π)) + 7/8
    Útil como detector de datasets rotos (orden de magnitud).
    """
    if T <= 0:
        return 0.0
    a = T / (2.0 * math.pi)
    if a <= 0:
        return 0.0
    return a * math.log(a) - a + 0.875

# ---------------- RED ROBUSTA ----------------
def http_get(url: str, retries: int = 3, timeout: int = 30) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "AcademicResearchBot/1.0",
            "Accept": "text/html",
        },
        method="GET",
    )
    last_err = None
    for i in range(retries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except (URLError, HTTPError) as e:
            last_err = e
            time.sleep(0.5 * (2 ** i))
    raise RuntimeError(f"Fallo de red persistente: {last_err}")

def detect_block(html: str) -> bool:
    h = html.lower()
    return any(x in h for x in [
        "captcha",
        "enable javascript",
        "cloudflare",
        "access denied",
        "forbidden",
        "rate limit",
    ])

# ---------------- PARSEO & FILTRADO ----------------
_gamma_re = re.compile(r"(?<![\d.])(\d+\.\d+)(?![\d.])")

def extract_table(html: str) -> str:
    """
    Intenta aislar una tabla que parezca contener 'gamma' / ceros.
    """
    lower = html.lower()
    pos = 0
    candidate_tables = []

    while True:
        s = lower.find("<table", pos)
        if s == -1:
            break
        e = lower.find("</table>", s)
        if e == -1:
            break
        candidate_tables.append(html[s:e+8])
        pos = e + 8

    if not candidate_tables:
        return html

    for t in candidate_tables:
        tl = t.lower()
        if any(k in tl for k in ("gamma", "imag", "zeta", "zero", "n")):
            return t

    return candidate_tables[0]

def parse_gammas(html: str) -> List[float]:
    if not html:
        return []
    if detect_block(html):
        raise RuntimeError("Bloqueo detectado (JS/CAPTCHA/Forbidden/RateLimit).")
    region = extract_table(html)

    vals: List[float] = []
    for m in _gamma_re.finditer(region):
        try:
            v = float(m.group(1))
            if v > 14.0:
                vals.append(v)
        except ValueError:
            pass
    return vals

def monotonic_filter(xs: List[float]) -> List[float]:
    """
    Conserva subsecuencia estrictamente creciente en el orden original.
    No reordena.
    """
    if not xs:
        return []
    out: List[float] = []
    last = 14.0
    for x in xs:
        if x > last:
            out.append(x)
            last = x
    return out

def validate_dataset(xs: List[float], strict: bool = True) -> Tuple[float, float]:
    """
    Valida:
    - monotonicidad estricta
    - gaps absurdos
    - densidad espectral via N(T)

    Retorna: (max_gap, density_ratio)
    """
    if not xs:
        raise RuntimeError("Dataset vacío.")

    # 1) Monotonicidad
    for i in range(len(xs) - 1):
        if xs[i] >= xs[i + 1]:
            raise RuntimeError(f"No monotónico en índice {i}: {xs[i]} >= {xs[i+1]}")

    # 2) Gaps
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    max_gap = max(gaps) if gaps else 0.0
    if max_gap > 50.0:
        msg = f"Gap sospechosamente grande: {max_gap}"
        if strict:
            raise RuntimeError(msg)
        else:
            print(f"[WARN] {msg}", file=sys.stderr)

    # 3) Densidad N(T): chequeo de orden de magnitud
    T0, T1 = xs[0], xs[-1]
    expected_span = _N_von_mangoldt(T1) - _N_von_mangoldt(T0)
    observed_span = float(len(xs) - 1)

    density_ratio = 1.0
    if expected_span > 1e-9:
        density_ratio = observed_span / expected_span

        # Tolerancia amplia: detector de datasets rotos, no prueba matemática.
        lo, hi = 0.5, 1.8
        if density_ratio < lo or density_ratio > hi:
            msg = f"Densidad inconsistente: observed/expected={density_ratio:.3f} (rango {lo}-{hi})"
            if strict:
                raise RuntimeError(msg)
            else:
                print(f"[WARN] {msg}", file=sys.stderr)

    return max_gap, density_ratio

# ---------------- ADQUISICIÓN ----------------
def acquire(k: int, page_size: int, sleep_s: float) -> Tuple[List[float], int]:
    got: List[float] = []
    pages = 0
    current_n = 1
    consecutive_empty = 0

    print(f"[INFO] Iniciando descarga de {k} ceros desde LMFDB...")

    while len(got) < k:
        url = f"{BASE_PUBLIC}?N={current_n}&limit={page_size}"

        html = http_get(url)

        raw = parse_gammas(html)
        clean = monotonic_filter(raw)

        # Deduplicación global por último valor guardado
        if got:
            last_stored = got[-1]
            clean = [x for x in clean if x > last_stored]

        if not clean:
            consecutive_empty += 1
            print(f"  > Pag {pages+1} vacia/filtrada (streak={consecutive_empty}).")
            if consecutive_empty >= 3:
                raise RuntimeError("Demasiadas paginas vacias consecutivas. Probable bloqueo o cambio de HTML.")
            time.sleep(max(1.0, sleep_s * 2.0))
            continue
        consecutive_empty = 0

        needed = k - len(got)
        take = clean[:needed]
        got.extend(take)
        pages += 1

        print(f"  > Pag {pages}: +{len(take)} ceros. Total: {len(got)}/{k}")

        current_n += page_size
        time.sleep(sleep_s)

    return got, pages

# ---------------- MAIN ----------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=100000)
    parser.add_argument("--page", type=int, default=100)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--strict", action="store_true", help="Abortar ante anomalias (recomendado).")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    start_t = time.time()
    gammas, pages = acquire(args.k, args.page, args.sleep)

    print("[INFO] Validando dataset...")
    max_gap, density_ratio = validate_dataset(gammas, strict=args.strict)

    print(f"[INFO] Guardando {len(gammas)} gammas en {ZEROS_FILE}...")
    with ZEROS_FILE.open("w", encoding="utf-8") as f:
        for g in gammas:
            f.write(f"{g:.15f}\n")

    meta = Meta(
        source=BASE_PUBLIC,
        fetched_at_utc=utc_now(),
        requested_k=args.k,
        acquired_k=len(gammas),
        page_size=args.page,
        pages_fetched=pages,
        sleep_seconds=args.sleep,
        output_file=str(ZEROS_FILE),
        output_sha256=sha256_file(ZEROS_FILE),
        first_gamma=float(gammas[0]),
        last_gamma=float(gammas[-1]),
        max_gap=float(max_gap),
        density_ratio_observed_expected=float(density_ratio),
    )

    META_FILE.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    elapsed = time.time() - start_t
    print(f"[OK] Completado en {elapsed:.2f}s.")
    print(json.dumps(asdict(meta), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
