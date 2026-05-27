import os
import re
import subprocess
import json
from pathlib import Path

# --- Rutas Gahenax ---
BASE_PATH = Path("c:/Users/jotam/OneDrive/Desktop/GahenaxAI/OEDA_HodgeRigidity")
AUDIT_REPORT = BASE_PATH / "results/mersenne/domino_wave/audit_wave_2_retro.md"
LL_BIN = BASE_PATH / "tools/mersenne-worker-rs/target/release/gahenax-ll.exe"
CHECKPOINT_DIR = BASE_PATH / "results/checkpoints"
GOLD_REPORT = BASE_PATH / "results/mersenne/domino_wave/gold_certification_report.md"

def extract_exponents(report_path):
    """Extrae los exponentes (p) de la tabla markdown del reporte de auditoría."""
    exponents = []
    with open(report_path, "r", encoding="utf-8") as f:
        for line in f:
            # Match: | 23201 | 1.1415 | **0.123232** | ...
            match = re.search(r"\|\s+(\d+)\s+\|", line)
            if match:
                p = int(match.group(1))
                # Filtramos p pequeños que no son los de la tabla (ej: ventana 0.1)
                if p > 1000:
                    exponents.append(p)
    return sorted(list(set(exponents)))

def verify_exponent(p):
    """Ejecuta el test LL local para el exponente p."""
    print(f"\n[🚀] Certificando M_{p}...")
    try:
        cmd = [str(LL_BIN), "--p", str(p), "--checkpoint-dir", str(CHECKPOINT_DIR)]
        # Forzamos utf-8 para evitar errores con los caracteres de indicatif (spinner/progress)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace')
        
        output = result.stdout
        if output is None: output = ""
        is_prime = "¡ÉXITO! M_" in output or "ES PRIMO" in output
        
        # Extraer residuo de 64 bits si existe en la salida o buscar el certificado
        res_match = re.search(r"gimps_residue_64\": \"([a-f0-9]+)\"", output) # Si lo imprime el cert
        res64 = res_match.group(1) if res_match else "unknown"
        
        return {
            "p": p,
            "status": "PRIME" if is_prime else "COMPOSITE",
            "res64": res64,
            "raw": output
        }
    except Exception as e:
        print(f"[❌] Error certificando p={p}: {e}")
        return {"p": p, "status": "ERROR", "error": str(e)}

def run_gold_phase():
    print("=== INICIANDO FASE DE ORO: CERTIFICACIÓN LL ===")
    exponents = extract_exponents(AUDIT_REPORT)
    
    if not exponents:
        print("[!] No se encontraron exponentes para certificar en el reporte.")
        return

    print(f"[INFO] Se han identificado {len(exponents)} candidatos para verificación.")
    
    results = []
    gold_found = []

    for p in exponents:
        res = verify_exponent(p)
        results.append(res)
        if res["status"] == "PRIME":
            print(f"  [🏆] ¡ORO ENCONTRADO! M_{p} es PRIMO.")
            gold_found.append(p)
        else:
            print(f"  [.] M_{p} es Compuesto. Residuo: {res.get('res64', 'N/A')}")

    # Generar Reporte Final
    with open(GOLD_REPORT, "w", encoding="utf-8") as gr:
        gr.write("# Fase de Oro: Certificación Lucas-Lehmer (Wave 2 Retro)\n\n")
        gr.write(f"- **Total Candidatos**: {len(exponents)}\n")
        gr.write(f"- **Primos Encontrados**: {len(gold_found)}\n\n")
        
        gr.write("## Tabla de Certificación\n\n")
        gr.write("| Exponente (p) | Resultado | Residuo (GIMPS 64-bit) |\n")
        gr.write("| :--- | :--- | :--- |\n")
        for r in results:
            status_str = f"**{r['status']}**" if r['status'] == "PRIME" else r['status']
            gr.write(f"| {r['p']} | {status_str} | `{r['res64']}` |\n")
        
        if gold_found:
            gr.write("\n## 🎯 HALLAZGOS DE ORO\n\n")
            for g in gold_found:
                gr.write(f"- **M_{g}** ha sido certificado como PRIMO localmente.\n")
            gr.write("\n> [!CAUTION]\n> Estos resultados deben ser validados independientemente por PrimeNet/GIMPS.\n")

    print(f"=== FASE DE ORO FINALIZADA. Reporte generado en {GOLD_REPORT.name} ===")

if __name__ == "__main__":
    run_gold_phase()
