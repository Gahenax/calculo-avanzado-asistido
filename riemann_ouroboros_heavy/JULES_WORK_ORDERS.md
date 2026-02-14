# JULES WORK ORDERS: OUROBOROS HEAVY — Parallel Zeta Farming
# ===========================================================
# Repo: https://github.com/Gahenax/calculo-avanzado-asistido (private)
# Branch base: master
#
# ESTRATEGIA: 4 tareas paralelas (una por ventana de zeros) + 1 tarea de ensamblaje.
# Cada tarea crea su propia branch, farma zeros, commitea .npy, y pushea.
# La tarea 5 mergea las 4 branches y corre el audit completo.

---

## TAREA 1 DE 5: Farm Window 1 (n=1000 → 11050, ~10050 zeros)

**Branch:** `farm/window-1`

### Instrucciones para Jules:

1. Clonar el repo y crear branch `farm/window-1` desde `master`.

2. Instalar dependencias:
```bash
pip install numpy scipy mpmath
```

3. Ejecutar el farmer:
```bash
cd riemann_ouroboros_heavy
python src/farm_window.py --n_start 1000 --n_end 11050 --window_id 1 --dps 50
```

4. Esto generará:
   - `outputs/zeros_window_1.npy` (~80 KB)
   - `outputs/spacings_window_1.npy` (~80 KB)
   - `outputs/farm_report_1.json`

5. Tiempo estimado: **2-3 horas**.

6. Al terminar, commitear y pushear:
```bash
git add outputs/zeros_window_1.npy outputs/spacings_window_1.npy outputs/farm_report_1.json
git commit -m "feat: farm window 1 complete (n=1000-11050, ~10050 zeros)"
git push origin farm/window-1
```

7. NO modificar ningún archivo fuente. Solo generar los .npy y el report.

---

## TAREA 2 DE 5: Farm Window 2 (n=12000 → 22050, ~10050 zeros)

**Branch:** `farm/window-2`

### Instrucciones para Jules:

1. Clonar el repo y crear branch `farm/window-2` desde `master`.

2. Instalar dependencias:
```bash
pip install numpy scipy mpmath
```

3. Ejecutar:
```bash
cd riemann_ouroboros_heavy
python src/farm_window.py --n_start 12000 --n_end 22050 --window_id 2 --dps 50
```

4. Generará: `zeros_window_2.npy`, `spacings_window_2.npy`, `farm_report_2.json`.

5. Tiempo estimado: **3-4 horas** (n más altos = más lentos).

6. Commitear y pushear en branch `farm/window-2`.

---

## TAREA 3 DE 5: Farm Window 3 (n=23000 → 33050, ~10050 zeros)

**Branch:** `farm/window-3`

### Instrucciones para Jules:

1. Branch `farm/window-3` desde `master`.

2. Ejecutar:
```bash
pip install numpy scipy mpmath
cd riemann_ouroboros_heavy
python src/farm_window.py --n_start 23000 --n_end 33050 --window_id 3 --dps 50
```

3. Generará: `zeros_window_3.npy`, `spacings_window_3.npy`, `farm_report_3.json`.

4. Tiempo estimado: **4-5 horas**.

5. Commitear y pushear en branch `farm/window-3`.

---

## TAREA 4 DE 5: Farm Window 4 (n=34000 → 44050, ~10050 zeros)

**Branch:** `farm/window-4`

### Instrucciones para Jules:

1. Branch `farm/window-4` desde `master`.

2. Ejecutar:
```bash
pip install numpy scipy mpmath
cd riemann_ouroboros_heavy
python src/farm_window.py --n_start 34000 --n_end 44050 --window_id 4 --dps 50
```

3. Generará: `zeros_window_4.npy`, `spacings_window_4.npy`, `farm_report_4.json`.

4. Tiempo estimado: **5-6 horas** (n más altos son los más lentos).

5. Commitear y pushear en branch `farm/window-4`.

---

## TAREA 5 DE 5: Assembly + Audit (EJECUTAR DESPUÉS DE TAREAS 1-4)

**Branch:** `farm/assembly`

### Instrucciones para Jules:

1. Crear branch `farm/assembly` desde `master`.

2. Mergear las 4 branches de farming:
```bash
git merge origin/farm/window-1 --no-edit
git merge origin/farm/window-2 --no-edit
git merge origin/farm/window-3 --no-edit
git merge origin/farm/window-4 --no-edit
```

3. Verificar que existen los 4 .npy:
```bash
ls riemann_ouroboros_heavy/outputs/zeros_window_*.npy
ls riemann_ouroboros_heavy/outputs/spacings_window_*.npy
```

4. Instalar dependencias y ejecutar assembly:
```bash
pip install numpy scipy mpmath
cd riemann_ouroboros_heavy
python src/assemble_and_audit.py --config config.json
```

5. Esto procesará ~40k zeros × 3 intensidades × 150 bloques/iter = ~1800 filas.
   Tiempo estimado: **5-10 minutos** (solo análisis, no mining).

6. Commitear todo:
```bash
git add outputs/
git commit -m "feat: OUROBOROS HEAVY assembly complete - 40k zeros, 4 windows, 3 intensities, full audit"
git push origin farm/assembly
```

7. Crear PR hacia `master` con título:
   "feat: OUROBOROS HEAVY — 40k zeta zeros GUE/Poisson audit"

---

## RESUMEN DE TIEMPOS

| Tarea | Ventana | Zeros | Rate estimada | Tiempo estimado |
|-------|---------|-------|---------------|-----------------|
| 1 | n=1000-11050 | 10,050 | ~1.0/s | 2-3 horas |
| 2 | n=12000-22050 | 10,050 | ~0.7/s | 3-4 horas |
| 3 | n=23000-33050 | 10,050 | ~0.5/s | 4-5 horas |
| 4 | n=34000-44050 | 10,050 | ~0.3/s | 5-6 horas |
| 5 | Assembly | 0 | N/A | 10 min |
| **Total** | **4 windows** | **40,200** | — | **~6h wall (paralelo)** |

Sin paralelismo: ~15-18 horas. Con Jules paralelo: ~6 horas wall-clock.
