#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ANTIGRAVITY_PROMPT_ODLYZKO_HIGH_ZEROS.py
=========================================
Prompt ejecutable para Jules/Antigravity.

Objetivo: Descargar y auditar las tablas de zeros altos de Odlyzko
(n~10^12, n~10^21, n~10^22) y comparar GUE universalidad a traves
de 22 ordenes de magnitud.

Uso: python ANTIGRAVITY_PROMPT_ODLYZKO_HIGH_ZEROS.py
"""

def build_prompt() -> str:
    return r"""
ANTIGRAVITY — ODLYZKO HIGH ZEROS AUDIT
========================================

OBJETIVO
Descargar, validar y auditar los zeros de Riemann a alturas extremas
usando las tablas de Odlyzko. Probar si GUE universalidad se mantiene
desde n=1 hasta n=10^22 (22 ordenes de magnitud).

REGLA 0 (ANTI-MAGIA)
Solo usar codigo existente en este repo. No inventar modulos.
Solo numpy + scipy + mpmath + stdlib.

CONTEXTO
El repo ya contiene:
  riemann_ouroboros_heavy/
    src/ODLYZKO_RIEMANN_PIPELINE.py   # descarga + parseo + validacion + unfold
    src/ODLYZKO_FULL_AUDIT.py         # gap-ratio KS audit completo
    src/controls.py                    # GUE/Poisson references
    src/metrics.py                     # gap_ratios, hist_entropy, ks_2samp
    src/entropy_reducer.py             # 3 intensidades
    src/audit.py                       # summary + robustness + outliers
    src/io_utils.py                    # StreamingCSVWriter
    data/zeros_odlyzko_zeros1.npy      # 100k zeros (ya descargados)
    data/spacings_odlyzko_zeros1.npy   # 100k spacings (ya calculados)

TABLAS OBJETIVO (Odlyzko, texto plano, sin JS/auth):

  zeros3: https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros3
          10,000 zeros empezando en n = 10^12 + 1
          Altura: t ~ 267,653,395,648

  zeros4: https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros4
          10,000 zeros empezando en n = 10^21 + 1
          Altura: t ~ 1.520...x10^20

  zeros5: https://www.dtc.umn.edu/~odlyzko/zeta_tables/zeros5
          10,000 zeros empezando en n = 10^22 + 1
          Altura: t ~ 1.520...x10^21

PASOS (ejecutar en orden):

1) BRANCH
   git checkout -b audit/high-zeros

2) INSTALAR
   pip install numpy scipy mpmath

3) DESCARGAR LAS 3 TABLAS
   cd riemann_ouroboros_heavy
   python src/ODLYZKO_RIEMANN_PIPELINE.py --table zeros3 --strict
   python src/ODLYZKO_RIEMANN_PIPELINE.py --table zeros4 --strict
   python src/ODLYZKO_RIEMANN_PIPELINE.py --table zeros5 --strict

   Esto generara en data/:
     zeros_odlyzko_zeros3.npy, spacings_odlyzko_zeros3.npy, meta_odlyzko_zeros3.json
     zeros_odlyzko_zeros4.npy, spacings_odlyzko_zeros4.npy, meta_odlyzko_zeros4.json
     zeros_odlyzko_zeros5.npy, spacings_odlyzko_zeros5.npy, meta_odlyzko_zeros5.json

4) AUDITAR CADA TABLA
   Para cada tabla (zeros3, zeros4, zeros5):

   a) Editar src/ODLYZKO_FULL_AUDIT.py:
      - Cambiar SPACINGS_PATH a "data/spacings_odlyzko_zerosX.npy"
      - Cambiar OUTPUT_DIR a "data/audit_zerosX"
      - Cambiar MERGED_CSV a "data/audit_zerosX/merged_zerosX.csv"
      - Cambiar REPORT_JSON a "data/audit_zerosX/audit_report_zerosX.json"
      - Cambiar OUTLIERS_CSV a "data/audit_zerosX/outliers_zerosX.csv"

   b) Ejecutar:
      python src/ODLYZKO_FULL_AUDIT.py

   ALTERNATIVA MEJOR: Crear ODLYZKO_MULTI_AUDIT.py que acepte argumentos:
      python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros3.npy --label zeros3
      python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros4.npy --label zeros4
      python src/ODLYZKO_MULTI_AUDIT.py --spacings data/spacings_odlyzko_zeros5.npy --label zeros5

5) COMPILAR RESULTADOS
   Crear un script o seccion que compare los resultados de las 5 tablas:

   Tabla    | Rango n        | vote_rate GUE | r_mean     | robust?
   ---------|----------------|---------------|------------|--------
   zeros1   | 1 - 100k       | ???%          | ~0.60      | ???
   zeros3   | 10^12          | ???%          | ???        | ???
   zeros4   | 10^21          | ???%          | ???        | ???
   zeros5   | 10^22          | ???%          | ???        | ???

   Si TODOS muestran vote_rate > 80%:
     CONCLUSION: "GUE_UNIVERSALITY_ACROSS_22_ORDERS_OF_MAGNITUDE"

   Si alguno falla:
     CONCLUSION: "DEVIATION_DETECTED_AT_SCALE_X"

6) COMMIT
   git add data/ src/
   git commit -m "feat: GUE universality audit across 22 orders of magnitude (n=1 to n=10^22)"
   git push origin audit/high-zeros

7) CREAR PR
   Titulo: "feat: Odlyzko high zeros - GUE universality n=1 to n=10^22"

SALIDAS ESPERADAS:
  data/audit_zeros3/audit_report_zeros3.json
  data/audit_zeros3/merged_zeros3.csv
  data/audit_zeros3/outliers_zeros3.csv
  (lo mismo para zeros4 y zeros5)

CRITERIO DE EXITO:
  vote_rate(zeta, GUE) > 80% en TODAS las tablas
  Robustez cross-intensity en TODAS las tablas

DISCLAIMER:
  Observacion estadistica != prueba de RH.
  Solo estamos verificando compatibilidad numerica con GUE.
"""

def main() -> None:
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(build_prompt())

if __name__ == "__main__":
    main()
