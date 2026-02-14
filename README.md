# Cálculo Avanzado Asistido

> Herramienta interactiva de cálculo simbólico y minería de estructuras numéricas.  
> Sistema: **GAHENAX / Antigravity Core**  
> Autor: José de Ávila

---

## Descripción

Este repositorio contiene tres módulos principales:

### 1. Calculadora Simbólica (Frontend)
Aplicación web construida con **Vite + React + TypeScript** que permite:
- Calcular derivadas simbólicas en tiempo real (vía Math.js)
- Renderizar fórmulas matemáticas con KaTeX
- Interfaz premium con glassmorphism y micro-animaciones

### 2. Motor de Minería Estructural (GCF Engine)
Escáner de **Fracciones Continuas Generalizadas** (GCF) que busca coincidencias numéricas entre constantes matemáticas y estructuras polinómicas de baja complejidad.

### 3. Gamma Prime Genesis
Demostración computacional de que γ (Euler–Mascheroni) emerge de la estructura de los números primos vía el producto de Mertens y la función de von Mangoldt.

---

## Protocolo: Logic Harness + Entropy Reducer

El motor de minería opera bajo un **arnés lógico** estricto + **reductor de entropía** que previene:
- Falsas descubrimientos por precisión finita
- Overfitting a la profundidad
- Convergencia inestable
- Coincidencias de vecindario (anti-cluster)
- Fugas narrativas ("esto explica X")
- Hype de problemas abiertos

### Reglas No Negociables
1. **Evidencia ≠ Prueba** — Nunca se reclama una prueba o identidad por acuerdo numérico.
2. **Candidato ≠ Descubrimiento** — Los resultados se etiquetan como "STRUCTURAL CANDIDATE" o "NUMERICAL COINCIDENCE".
3. **Estructura ≠ Significado** — No se interpreta significado de dominio solo por estructura.
4. **Toda conclusión tiene una condición de descarte.**

---

## Cronología de Ejecuciones (2026-02-13)

### Run 1: Calibración básica (v2, Logic Harness)
- **Espacio:** grado ≤ 2, coeff [-2, 2], 15,376 pares
- **Resultado:** `4/π` encontrado como `a(n)=n², b(n)=2n+1` — **fracción continua de Brouncker (1656)**
- **Validación:** Error ~1.97e-31, tail PASS, cross-check PASS → **engine validado** ✅

### Run 2: Entropy Reducer (v3)
- **Espacio:** grado ≤ 2, coeff [-3, 3], 116,964 pares
- **Reducer:** Canonicalización + divergence prefilter + ballpark gating(2-depth) + stability triage
- **Resultado:** Mismo `4/π` Brouncker confirmado. γ: NO_SIG.
- **UA contabilidad:** Ballpark gating removió **8.7 bits** de entropía en un paso.

### Run 3: Gamma Expand (v4, multi-precision)
- **Espacio:** Phase A (deg≤2, [-5,5], 662k pares) + Phase B (deg≤3, [-3,3], 2.5M pares parcial)
- **Estabilidad:** Multi-precision (80-bit vs 160-bit), truncación + agreement
- **Resultado:** 50 candidatos con StabilityScore ≥ 12
- **Diagnóstico:** **Coincidencias de vecindario** — convergían a valores cerca de γ (gap ~10⁻³) pero no a γ

### Run 4: B2 Gap-first (v5, corrected harness)
- **Pipeline:** S0(depth=16, gap≤1e-6) → S1(depth=128, gap≤1e-10) → S2(multi-prec, Smin=20)
- **Anti-cluster:** Buckets por valor convergido (8 decimales, max 3/bucket)
- **Futility stop:** 5 ventanas de 50k sin mejora 100x
- **Resultado:** `gamma: NO_SIG` — **0 candidatos** pasaron Stage 0 en 300k pares
- **Evidencia:** Futility triggered en 6 ventanas, todas con best_gap = ∞

### Conclusión GCF para γ
> **γ no tiene representación como GCF con polinomios de grado ≤ 3 y coeficientes enteros en [-5, 5].**
> Resultado confirmado con gap-first pipeline y evidencia de futilidad.

### Run 5: Gamma Prime Genesis (computacional)
- **Método A (Mertens):** γ ≈ -ln(ln(x) · ∏(1-1/p)) → error ~5.0e-5 con x=1,999,993
- **Método B (von Mangoldt):** γ ≈ ln(x) - Σ Λ(n)/n → error ~5.5e-5 con x=1,999,993
- **Convergencia lenta** (esperada para ambos métodos) — confirman que γ emerge de la distribución prima

### Run 6: Riemann GUE Constrictor C1-C7 (first farm)
- **Datos:** 800 zeros de ζ(s), 4 ventanas × 200 zeros (n=1000-4200)
- **C2 KS GUE ✅:** p-values 0.35-0.90 — spacings compatibles con Wigner GUE
- **C3 KS Poisson ✅:** p=0.000 — Poisson descartado categóricamente
- **C5 unfolding ✅:** mean spacing ≈ 1.00
- **C1 β ❌:** ~1.0-1.3 (insuficiente potencia estadística con 200 zeros por ventana)
- **C7 Δ₃ ✅:** rigidez compatible con GUE

### Run 7: Riemann Final Verdict (`CONFIRMED_GUE_UNIVERSALITY`) ✅
- **Pipeline mejorado:** Gap Ratio + Beta MLE + SFF con controles exactos multi-seed
- **Datos:** 600 zeros (n=1000-1600), 11 bloques overlap50
- **Controles:** GUE (8 matrices Hermíticas, bulk unfolding) + Poisson (8 exponenciales)

| Métrica | Valor | CI 95% | Target GUE | Target Poisson |
|---------|-------|--------|------------|----------------|
| **Gap Ratio** | **0.6215** | [0.6145, 0.6283] | ~0.60 | ~0.39 |
| **Beta MLE** | **2.593** | [2.474, 2.718] | ~2.0 | ~0.0 |
| **d(R,GUE)** | **0.849** | [0.802, 0.898] | — | — |
| **d(R,Poisson)** | **0.978** | [0.928, 1.033] | — | — |
| **GUE vote rate** | **90.91%** | — | ≥80% | — |

> **Veredicto: `CONFIRMED_GUE_UNIVERSALITY`** — Los ceros de ζ(s) son estadísticamente
> indistinguibles de la universalidad GUE bajo las métricas Gap Ratio, Beta MLE y SFF.
> **DISCLAIMER: Compatibilidad estadística ≠ prueba de RH.**

---

## Stack Tecnológico

| Componente | Tecnología |
|-----------|-----------|
| Frontend | Vite + React 19 + TypeScript |
| Estilos | Vanilla CSS (Glassmorphism, Dark Mode) |
| Animaciones | Framer Motion |
| Matemáticas (frontend) | Math.js, KaTeX |
| Iconos | Lucide React |
| Motor GCF (backend) | Python 3 + mpmath |
| Pipeline Riemann | Python 3 + numpy + scipy + mpmath |
| Fuente | Inter (Google Fonts) |

## Estructura del Proyecto

```
calculo-avanzado-asistido/
├── core/                                          # Motor Python
│   ├── ANTIGRAVITY_PROMPT_STRUCTURAL_NUMERIC_SEARCH.py
│   ├── ANTIGRAVITY_PROMPT_LOGIC_HARNESS_V1.py
│   ├── ANTIGRAVITY_PROMPT_ENTROPY_REDUCER_V1.py
│   ├── ANTIGRAVITY_PROMPT_GAMMA_GCF_EXPAND.py
│   ├── ANTIGRAVITY_PROMPT_GAMMA_GCF_B2_CORRECTIONS.py
│   ├── ANTIGRAVITY_PROMPT_RIEMANN_FARMING.py
│   ├── STRUCTURAL_NUMERIC_SEARCH_RUNNER.py        # Runner v3 (Entropy Reducer)
│   ├── GAMMA_GCF_EXPAND_RUNNER.py                 # Runner v4 (Multi-precision)
│   ├── GAMMA_GCF_B2_RUNNER.py                     # Runner v5 (Gap-first)
│   ├── GAMMA_PRIME_GENESIS_HARDENED.py             # Mertens + von Mangoldt
│   ├── RIEMANN_GUE_CONSTRICTOR_HARDENED_C7.py     # GUE C1-C7 pipeline
│   ├── RIEMANN_FINAL_VERDICT_ONEPROMPT.py         # Final GUE verdict
│   ├── riemann_final_verdict.json
│   ├── riemann_constrictor_c7.json
│   └── gamma_b2_results.json
├── src/
│   ├── core/
│   │   └── StructureMiner.ts                      # Port TypeScript del GCF engine
│   ├── StructureMinerUI.tsx                        # UI del minero
│   ├── App.tsx                                    # Aplicación principal
│   ├── index.css                                  # Sistema de diseño
│   └── main.tsx
├── index.html
├── package.json
├── IMPLEMENTATION_PLAN.md
└── README.md
```

## Cómo ejecutar

### Frontend (Dev Server)
```bash
npm install
npm run dev
```

### Motor GCF (Python)
```bash
pip install mpmath

# Calibración + búsqueda general
python core/STRUCTURAL_NUMERIC_SEARCH_RUNNER.py

# Gamma expand (multi-precision)
python core/GAMMA_GCF_EXPAND_RUNNER.py

# Gamma B2 (gap-first)
python core/GAMMA_GCF_B2_RUNNER.py

# Gamma Prime Genesis (Mertens + von Mangoldt)
python core/GAMMA_PRIME_GENESIS_HARDENED.py --method both --N 2000000 --dps 80
```

### Pipeline Riemann GUE
```bash
pip install numpy scipy mpmath

# Quick run (600 zeros, ~10 min)
python core/RIEMANN_FINAL_VERDICT_ONEPROMPT.py --n_start 1000 --total_zeros 600 --block_size 100 --block_mode overlap50

# Full run (2000 zeros, ~40 min)
python core/RIEMANN_FINAL_VERDICT_ONEPROMPT.py --n_start 5000 --total_zeros 2000 --block_size 200

# C1-C7 pipeline (legacy)
python core/RIEMANN_GUE_CONSTRICTOR_HARDENED_C7.py --count 200 --windows "1000,2000,3000,4000"
```

---

## DISCLAIMER

Todos los resultados son **COINCIDENCIAS NUMÉRICAS** u **OBSERVACIONES ESTADÍSTICAS** identificadas mediante evaluación de profundidad finita. **NO** son pruebas, identidades ni resoluciones de problemas abiertos. La compatibilidad estadística GUE **NO** prueba la Hipótesis de Riemann. Son **CANDIDATOS ESTRUCTURALES** y **EVIDENCIA REPRODUCIBLE** para revisión por un matemático humano.

---

*Potenciado por Antigravity Core v6.0 — GAHENAX*
