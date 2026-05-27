#!/usr/bin/env python3
"""
GAHENAX AUTONOMOUS MANAGER (Interceptor v3.0)
============================================
Agente de gestión soberana para la búsqueda de Primos de Mersenne.
Monitoriza resultados, ejecuta analítica y mantiene la integridad del Ledger.

Protocolo: Domino-Wave v2.0
Autor: Antigravity (Gahenax AI)
"""

import os
import json
import time
import subprocess
import sys
import io
from pathlib import Path
from datetime import datetime

# Forzar codificación UTF-8 para evitar errores con emojis en Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- Configuración de Rutas (Gahenax v3.0) ---
BASE_DIR = Path("c:/Users/jotam/OneDrive/Desktop/GahenaxAI/OEDA_HodgeRigidity")
RESULTS_DIR = BASE_DIR / "results/mersenne/domino_wave"
LEDGER_PATH = BASE_DIR / "results/mersenne/cert_ledger_seismic.jsonl"
LOG_PATH = BASE_DIR / "results/mersenne/MERSENNE_OPERATIONAL_LOG.md"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Configuration
AGENT_SIG = "Gahenax-Antigravity-v3.1-SIG-Reactive"
REACTIVE_THRESHOLD = 0.95
JULES_ORDERS_DIR = BASE_DIR / "jules_orders"

# Keep track of triggered p's to avoid duplicate LL tests
triggered_ps = set()

def log_event(message: str):
    """Añade un evento al log operacional."""
    timestamp = datetime.now().strftime("%H:%M")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n- **{timestamp}**: {message}")
    print(f"[{timestamp}] {message}")

def run_pipeline():
    """Ejecuta el pipeline de analítica y dashboard."""
    print("Running Analytics Pipeline...")
    try:
        # 1. Run Analytics Audit
        subprocess.run([
            "python", str(SCRIPTS_DIR / "interceptor_analytics_v3.py"),
            "--dir", str(RESULTS_DIR),
            "--out", str(RESULTS_DIR / "audit_auto.md")
        ], check=True)
        
        # 2. Run Dashboard Generator
        subprocess.run([
            "python", str(SCRIPTS_DIR / "dashboard_generator.py"),
            "--dir", str(RESULTS_DIR),
            "--out", str(RESULTS_DIR / "interceptor_dashboard_live.png")
        ], check=True)
        
        log_event("PIPELINE_AUTO_UPDATE 🔄. Dashboard y Auditoría actualizados.")
    except Exception as e:
        log_event(f"PIPELINE_ERROR ❌: {str(e)}")

def trigger_ll_test(p, score):
    """Genera una orden de trabajo reactiva para un test LL profundo."""
    if p in triggered_ps:
        return
    
    order_id = f"REACTIVE-LL-{p}"
    order_path = JULES_ORDERS_DIR / f"JULES_ORDER_{order_id}.json"
    
    order = {
        "order_id": order_id,
        "skill": "mersenne-interceptor-v3",
        "target": f"ANOMALY_C_CERTIFICATION_{p}",
        "parameters": {
            "p_start": p,
            "p_end": p,
            "method": "ll",
            "notes": f"Reactive trigger based on spectral score {score:.4f}"
        },
        "priority": "URGENT",
        "callback_hook": "autonomous_manager.py"
    }
    
    with open(order_path, "w") as f:
        json.dump(order, f, indent=4)
    
    log_event(f"REACTIVE_TRIGGER ⚡: p={p} (Score={score:.4f}). Orden {order_id} generada.")
    triggered_ps.add(p)

def process_telemetry():
    """Analiza la telemetría en busca de anomalías para disparar la Capa C."""
    tele_files = list(RESULTS_DIR.glob("block_telemetry_*.jsonl"))
    triggers_count = 0
    
    for tele_file in tele_files:
        try:
            with open(tele_file, "r") as f:
                for line in f:
                    event = json.loads(line)
                    score = event.get("spectral_score", 0.0)
                    p = event.get("p")
                    action = event.get("action", "")
                    
                    if score >= REACTIVE_THRESHOLD and action == "SPECTRAL_LOW_PRIORITY":
                        trigger_ll_test(p, score)
                        triggers_count += 1
        except Exception as e:
            print(f"Error processing telemetry {tele_file}: {e}")
    return triggers_count

def process_results():
    """Busca nuevos bloques y los agrega al ledger si son hallazgos."""
    blocks = list(RESULTS_DIR.glob("block_result_*.json"))
    processed_count = 0
    
    # Cargar p's ya en el ledger para evitar duplicados
    existing_ps = set()
    if LEDGER_PATH.exists():
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "p" in data:
                        existing_ps.add(data["p"])
                except:
                    continue

    for block_file in blocks:
        try:
            with open(block_file, "r") as f:
                data = json.load(f)
                
            # Extraer hallazgos
            findings = [r for r in data.get("results", []) if r.get("is_prime") is True]
            
            for fnd in findings:
                p = fnd.get("p")
                if p not in existing_ps:
                    log_event(f"FINDING_DETECTED 💡: p={p} certificado en bloque {data.get('block_id')}")
                    
                    # Certificar en el Ledger
                    entry = {
                        "timestamp": datetime.now().isoformat(),
                        "type": "INVARIANCE_CERT",
                        "p": p,
                        "label": f"GL-{p}",
                        "gl_class": "GL-P",
                        "spectral_score": fnd.get("spectral_score", 0.0),
                        "interceptor_version": "v3.0-FFT",
                        "agent_signature": AGENT_SIG,
                        "status": "SEALED",
                        "protocol": "I(p)-Quantum-Resonance-v3.0"
                    }
                    
                    with open(LEDGER_PATH, "a", encoding="utf-8") as f_ledger:
                        f_ledger.write(json.dumps(entry) + "\n")
                    
                    existing_ps.add(p)
                    processed_count += 1
        except Exception as e:
            print(f"Error processing {block_file}: {e}")

    return processed_count

def main():
    log_event("AUTONOMOUS_MANAGER_START 🚀. Agente Antigravity asume control operacional.")
    
    # Primera corrida de limpieza
    process_results()
    run_pipeline()
    
    print("Manager is active. Monitoring for result updates... (Ctrl+C to stop)")
    try:
        while True:
            new_work = process_results()
            new_triggers = process_telemetry()
            
            if new_work > 0 or new_triggers > 0:
                run_pipeline()
            time.sleep(30)
    except KeyboardInterrupt:
        log_event("AUTONOMOUS_MANAGER_STOP 🛑. Control devuelto a modo manual.")

if __name__ == "__main__":
    main()
