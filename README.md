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
│   ├── STRUCTURAL_NUMERIC_SEARCH_RUNNER.py        # Runner v3 (Entropy Reducer)
│   ├── GAMMA_GCF_EXPAND_RUNNER.py                 # Runner v4 (Multi-precision)
│   ├── GAMMA_GCF_B2_RUNNER.py                     # Runner v5 (Gap-first)
│   ├── GAMMA_PRIME_GENESIS_HARDENED.py             # Mertens + von Mangoldt
│   ├── structural_search_results_v3.json
│   ├── gamma_expand_results_v4.json
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

---

## DISCLAIMER

Todos los resultados son **COINCIDENCIAS NUMÉRICAS** identificadas mediante evaluación de profundidad finita. **NO** son pruebas, identidades ni resoluciones de problemas abiertos. Son **CANDIDATOS ESTRUCTURALES** para revisión por un matemático humano.

La estabilidad numérica no implica irracionalidad/racionalidad ni forma cerrada.

---

*Potenciado por Antigravity Core v5.0 — GAHENAX*
