# Cálculo Avanzado Asistido

> Herramienta interactiva de cálculo simbólico y minería de estructuras numéricas.  
> Sistema: **GAHENAX / Antigravity Core**  
> Autor: José de Ávila

---

## Descripción

Este repositorio contiene dos módulos principales:

### 1. Calculadora Simbólica (Frontend)
Aplicación web construida con **Vite + React + TypeScript** que permite:
- Calcular derivadas simbólicas en tiempo real (vía Math.js)
- Renderizar fórmulas matemáticas con KaTeX
- Interfaz premium con glassmorphism y micro-animaciones

### 2. Motor de Minería Estructural (GCF Engine)
Escáner de **Fracciones Continuas Generalizadas** (GCF) que busca coincidencias numéricas entre constantes matemáticas y estructuras polinómicas de baja complejidad.

**Características del motor:**
- Evaluación de GCF con recurrencia hacia atrás
- Test de estabilidad multi-profundidad (N, 2N, 4N, 8N)
- Test de sensibilidad de cola (tail sensitivity)
- Cross-check contra targets cercanos
- Rechazo de secuencias divergentes/oscilatorias

---

## Protocolo: Logic Harness v1.0

El motor de minería opera bajo un **arnés lógico** estricto que previene:
- Falsas descubrimientos por precisión finita
- Overfitting a la profundidad
- Convergencia inestable
- Fugas narrativas ("esto explica X")
- Hype de problemas abiertos

### Pasos del Protocolo

| Paso | Nombre | Descripción |
|------|--------|-------------|
| 0 | SPEC | Restablecer targets, clase de estructura, límites |
| 1 | FAILURE MODES | Checklist explícito de modos de fallo |
| 2 | TEST PLAN | Multi-depth + tail sensitivity + cross-check + calibración |
| 3 | SEARCH | Filtro rápido + pipeline completo, tracking de estadísticas |
| 4 | OUTPUT CONTRACT | Reporte estricto por candidato |
| 5 | NO HYPE CLOSURE | Resumen conservador |

### Reglas No Negociables
1. **Evidencia ≠ Prueba** — Nunca se reclama una prueba o identidad por acuerdo numérico.
2. **Candidato ≠ Descubrimiento** — Los resultados se etiquetan como "STRUCTURAL CANDIDATE" o "NUMERICAL COINCIDENCE".
3. **Estructura ≠ Significado** — No se interpreta significado de dominio (física/bio/finanzas) solo por estructura.
4. **Toda conclusión tiene una condición de descarte.**

---

## Resultados: Ejecución del 2026-02-13

### Configuración
- Clase de estructura: GCF con polinomios de grado ≤ 2
- Coeficientes: [-2, -1, 0, 1, 2]
- Profundidades: [40, 80, 160, 320]
- Precisión: 30 dígitos decimales (mpmath)
- Espacio de búsqueda: 15,376 pares (a, b)

### Targets Escaneados

| Target | Valor | Candidatos | Status |
|--------|-------|------------|--------|
| φ (calibración) | 1.618033... | 0 | NO_SIG |
| π (calibración) | 3.141592... | 0 | NO_SIG |
| e (calibración) | 2.718281... | 0 | NO_SIG |
| 4/π | 1.273239... | **1** | ✅ CANDIDATE |
| 1/π | 0.318309... | 0 | NO_SIG |
| γ (Euler-Mascheroni) | 0.577215... | 0 | NO_SIG |

### Candidato Encontrado

```
STRUCTURAL CANDIDATE #1
-----------------------
Target:             4/π
a(n):               n²
b(n):               2n + 1
Depths:             [40, 80, 160, 320]
Stability deltas:   [0.0, 0.0, 0.0]
Abs error:          ~1.97e-31
Rel error:          ~1.55e-31
Tail sensitivity:   PASS (metric=0.0)
Cross-check:        PASS (ratio=5.07e+26)
VERDICT:            CANDIDATE
DISCARD CONDITION:  Invalidate if higher-depth eval diverges or
                    tail sensitivity fails at depth>320.
```

> **Nota:** Esta es la fracción continua de Brouncker (1656), una identidad conocida.  
> Su detección valida el correcto funcionamiento del motor.

### Análisis
- La calibración funcionó: φ, π, e no producen candidatos con coeficientes [-2,2] (esperado).
- 4/π fue encontrado correctamente → **validación del engine**.
- γ no produjo candidatos → resultado conservador y correcto.

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
├── core/                                    # Motor Python
│   ├── ANTIGRAVITY_PROMPT_STRUCTURAL_NUMERIC_SEARCH.py
│   ├── ANTIGRAVITY_PROMPT_LOGIC_HARNESS_V1.py
│   ├── STRUCTURAL_NUMERIC_SEARCH_RUNNER.py  # Runner principal
│   ├── structural_search_results.json       # Resultados
│   └── search_output.log                    # Log completo
├── src/
│   ├── core/
│   │   └── StructureMiner.ts                # Port TypeScript del GCF engine
│   ├── StructureMinerUI.tsx                  # UI del minero
│   ├── App.tsx                              # Aplicación principal
│   ├── index.css                            # Sistema de diseño
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
python core/STRUCTURAL_NUMERIC_SEARCH_RUNNER.py
```

---

## DISCLAIMER

Todos los resultados son **COINCIDENCIAS NUMÉRICAS** identificadas mediante evaluación de profundidad finita. **NO** son pruebas, identidades ni resoluciones de problemas abiertos. Son **CANDIDATOS ESTRUCTURALES** para revisión por un matemático humano.

---

*Potenciado por Antigravity Core v2.0 — GAHENAX*
