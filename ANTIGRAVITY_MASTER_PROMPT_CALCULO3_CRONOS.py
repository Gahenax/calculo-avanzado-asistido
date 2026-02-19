#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ANTIGRAVITY_MASTER_PROMPT_CALCULO3_CRONOS.py
===========================================

Ejecutable que IMPRIME un único prompt maestro para Antigravity, consolidando
todo lo acordado:

1) Unificar ceros en ALL_ZEROS_FINAL.json (dedupe + orden)
2) Ejecutar Rescue Lab (Explore/Focus/Verify) con backend mpmath
3) Ejecutar CRONOS Auditor (Wigner spacing + SFF con ensemble averaging)
4) Emitir veredicto GUE-compatible usando ranking KS (no umbral mágico)
5) Exportar artefactos (json + png) y un reporte final reproducible

Uso:
  python3 ANTIGRAVITY_MASTER_PROMPT_CALCULO3_CRONOS.py > PROMPT_ANTIGRAVITY.txt
"""

PROMPT = r"""
[ANTIGRAVITY | MASTER JOB | CALCULO 3 -> CRONOS FINAL AUDIT]

OBJETIVO GENERAL
- Consolidar un dataset unificado y deduplicado de ceros (t_n) en la línea crítica.
- Validar estadística de repulsión (Nearest-Neighbor Spacing vs Wigner/Poisson) y construir SFF (Spectral Form Factor) con ensemble averaging.
- Producir artefactos finales reproducibles para el reporte: JSONs + plots + veredicto.

ENTRADAS ESPERADAS (EN LA CARPETA DE TRABAJO)
A) rescue/mining outputs (uno o varios):
   - rescue_*.json (salida del laboratorio de rescate)
   - drill_*.json  (salida de drill local si aplica)
   - base_*.json   (dataset base, si existe)
B) Alternativamente, si ya existe unificado:
   - ALL_ZEROS_FINAL.json con lista completa de ceros.

FORMATO ACEPTADO PARA LISTAS DE CEROS (t_n)
- Lista plana: [t1, t2, ...]
- Diccionario: {"zeros":[...]} o {"t":[...]} o {"data":[...]} o {"values":[...]}

RESTRICCIONES Y CRITERIOS (CANON)
1) No declarar “GUE puro” por retórica.
2) “Completitud > 100%” no es victoria por sí sola: puede ser subestimación local de N_asym(T).
3) Veredicto principal: ranking de distancias KS
   - Se considera GUE-compatible fuerte si ks_gue es claramente menor que ks_poisson y menor que ks_goe,
     y ese ranking es estable bajo subventanas/submuestreo.
4) KS calculado sin SciPy es aproximado: usarlo para ranking y robustez, no como p-valor absoluto.

ENTREGABLES FINALES (OBLIGATORIOS)
1) ALL_ZEROS_FINAL.json (lista deduplicada y ordenada)
2) cronos_report.json (KS + stats + meta SFF)
3) wigner_spacing.png
4) sff.png
5) final_verdict.md (resumen ejecutivo: resultados + estabilidad + conclusiones + próximos pasos)

PASO 0: SANIDAD DE ENTORNO
- Verificar dependencias:
  pip install numpy mpmath matplotlib
- Usar Python 3.10+ si es posible.

PASO 1: UNIFICACIÓN DEL DATASET
Si ALL_ZEROS_FINAL.json NO existe:
1.1) Buscar automáticamente archivos JSON candidatos en el directorio actual:
     - patrones sugeridos: *.json (filtrar por los que contengan listas de floats razonables)
1.2) Extraer todos los ceros t_n desde todas las fuentes detectadas.
1.3) Unificar en una sola lista.
1.4) Ordenar ascendente.
1.5) Deduplicar con tolerancia:
     - dedupe_tol = 1e-10 (por defecto)
1.6) Guardar:
     - ALL_ZEROS_FINAL.json con formato {"zeros":[...]} y metadatos auxiliares en un archivo separado:
       ALL_ZEROS_FINAL_meta.json (fuentes, conteos por fuente, tol usada, t_min/t_max).

PASO 2: (OPCIONAL) RESCUE LAB PARA BLOQUE OBJETIVO
Si el objetivo es rescatar/validar específicamente [1314,1414] o [1414,1514]:
2.1) Ejecutar el laboratorio (si está disponible) con parámetros canónicos:
     - alpha_explore = 0.12
     - bin_width = 0.5
     - deficit_threshold = 0.10
     - focus_rounds = 2
     - dps_base = 50
     - dps_focus = 80
2.2) Exportar un JSON de run:
     - rescue_<T0>_<T1>.json
2.3) Incorporar ceros del run al ALL_ZEROS_FINAL.json (repetir dedupe+orden).

PASO 3: CRONOS AUDITOR (WIGNER + SFF)
3.1) Cargar ALL_ZEROS_FINAL.json
3.2) Deduplicar y ordenar (idempotente)
3.3) Unfolding:
     - Mapear t -> E = N_asym(t) para remover densidad media.
     - Asegurar E estrictamente creciente (monotonicidad) para evitar empates numéricos.
3.4) Nearest Neighbor Spacing:
     - s_i = (E_{i+1} - E_i) / mean(gaps)
     - Construir histograma density y superponer:
       - Wigner GUE: P(s) = (32/pi^2) s^2 exp(-4 s^2 / pi)
       - Wigner GOE: P(s) = (pi/2) s exp(-pi s^2 / 4)
       - Poisson:     P(s) = exp(-s)
     - Calcular KS aproximado (ranking):
       - ks_gue, ks_goe, ks_poisson
     - Guardar wigner_spacing.png
3.5) SFF (Spectral Form Factor) con ensemble averaging:
     - Definir ventanas deslizantes sobre E:
       - window_size recomendado: 180–240 (default 200)
       - step recomendado: 30–50 (default 50)
     - Para t_grid en [0, t_max] (default t_max=80, n_t=500):
       - K(t) = < | sum_{n in window} exp(i t (E_n - mean(window))) |^2 / window_size >_windows
     - Guardar sff.png
3.6) Robustez (OBLIGATORIA):
     - Repetir KS ranking en subventanas:
       - Dividir E en 2 mitades y recalcular ks_* por mitad.
       - Dividir E en 5 subventanas (si N permite) y reportar ks_* por subventana.
     - Reportar:
       - media/mediana y rango de ks_gue, ks_goe, ks_poisson por subventanas.
     - Criterio de estabilidad:
       - el ranking ks_gue < ks_goe < ks_poisson (o al menos ks_gue < min(ks_goe, ks_poisson))
         debe sostenerse en la mayoría de subventanas.

PASO 4: VEREDICTO FINAL (final_verdict.md)
El veredicto NO debe usar un umbral fijo tipo ks_gue < 0.05 como “ley”.
Debe usar:
- Ranking KS global + estabilidad por subventanas.
- Confirmación cualitativa: histograma con repulsión en s=0 (sube desde 0).
- SFF: presencia o ausencia de dip->rampa->plateau, con notas de sensibilidad a window_size/step.

Estructura sugerida de final_verdict.md:
1) Resumen ejecutivo:
   - n_zeros, rango t_min/t_max
   - ks_gue/ks_goe/ks_poisson global
   - estabilidad por subventanas
2) Wigner spacing:
   - interpretación (repulsión vs Poisson)
3) SFF:
   - descripción de la curva, región de rampa si existe
4) Limitaciones:
   - KS aproximado si no se usa SciPy
   - unfolding N_asym como aproximación
5) Conclusión:
   - “GUE-compatible fuerte / plausible / no concluyente”
6) Próximos pasos:
   - ajustar window_size/step
   - ampliar bloque [1414,1514] para persistencia
   - opcional: usar SciPy kstest y/o bootstrap formal

SALIDAS NOMBRADAS (CANON)
- ALL_ZEROS_FINAL.json
- ALL_ZEROS_FINAL_meta.json
- cronos_report.json
- wigner_spacing.png
- sff.png
- final_verdict.md

EJECUCIÓN
- Implementar un único script runner (o una secuencia de comandos) que ejecute Pasos 1 a 4.
- Imprimir al final un resumen en JSON por stdout con:
  - n_zeros, ks_gue, ks_goe, ks_poisson, ranking_estable(bool), paths de artefactos.

FIN DEL MASTER JOB
"""

def main() -> None:
    print(PROMPT.strip() + "\n")

if __name__ == "__main__":
    main()
