import os
import time
import subprocess
from pathlib import Path

# Anclas Ground-Truth
# Anchos de banda: 2,000 exponentes centrados sobre los números primos históricos
WAVES = [
    {"name": "Wave_M49", "start": 74206281, "end": 74208281, "truth": 74207281},
    {"name": "Wave_M50", "start": 77231917, "end": 77233917, "truth": 77232917},
    {"name": "Wave_M51", "start": 82588933, "end": 82590933, "truth": 82589933},
]

def run_cross_validation():
    print("\n" + "="*60)
    print("=== OEDA V4: INICIANDO VALIDACIÓN CRUZADA (M49 - M51) ===")
    print("="*60)
    
    worker_script = Path(__file__).parent / "mersenne_domino_worker.py"
    out_dir = Path(__file__).parent.parent / "results" / "mersenne" / "domino_wave"
    
    for i, wave in enumerate(WAVES):
        print(f"\n>> {wave['name']} - Objetivo OEDA: Aislar candidato [p={wave['truth']}]")
        cmd = [
            "python", str(worker_script),
            "--block_id", str(4900 + i), # 4900, 4901, 4902 para tracking
            "--p_start", str(wave["start"]),
            "--p_end", str(wave["end"]),
            "--method", "spectral",
            "--threshold", "0.85",
            "--out", str(out_dir)
        ]
        
        t0 = time.time()
        print(f"Lanzando Turbina: {' '.join(cmd)}")
        cp = subprocess.run(cmd)
        
        if cp.returncode != 0:
            print(f"[!] Alerta: Fallo crítico en el bloque {wave['name']}.")
        
        print(f"<< {wave['name']} Finalizada en {time.time()-t0:.2f}s")
        
    print("\n" + "="*60)
    print("=== PROTOCOLO CV M49-M51 CULMINADO EXITOSAMENTE ===")
    print(f"Inspeccione '{out_dir}' para auditar la pureza del Z-Score y fallos del pipeline.")
    print("="*60)

if __name__ == "__main__":
    run_cross_validation()
