import os
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# --- Configuración de Gahenax v3.0 ---
BASE_PATH = Path("c:/Users/jotam/OneDrive/Desktop/GahenaxAI/OEDA_HodgeRigidity")
ENV_PATH = BASE_PATH / ".env"
JULES_ORDERS_DIR = Path("c:/Users/jotam/OneDrive/Desktop/GahenaxAI/jules_orders")
OPERATIONAL_LOG = BASE_PATH / "results/mersenne/MERSENNE_OPERATIONAL_LOG.md"

# Cargar variables de entorno
load_dotenv(ENV_PATH)

JULES_API_KEY = os.getenv("UNKNOWN_JULES_API_KEY")
JULES_API_ENDPOINT = "https://jules.gahenax.ai/api/v1/submit" # Asignado por arquitectura Sigil

def log_event(message: str):
    """Registra el evento en el log operativo de Gahenax."""
    timestamp = os.popen("date /t").read().strip() + " " + os.popen("time /t").read().strip()
    with open(OPERATIONAL_LOG, "a", encoding="utf-8") as f:
        f.write(f"- **[{timestamp}]** {message}\n")
    print(f"[GAHENAX] {message}")

def deploy_mission(mission_file: str, payload_zip: str):
    """Envía la misión al clúster Jules."""
    if not JULES_API_KEY:
        print("[ERROR] JULES_API_KEY no encontrada en .env")
        return

    condor_path = JULES_ORDERS_DIR / mission_file
    payload_path = JULES_ORDERS_DIR / payload_zip

    if not condor_path.exists():
        print(f"[ERROR] Manifiesto no encontrado: {condor_path}")
        return

    print(f"[INFO] Iniciando despacho de Misión: {mission_file}")
    
    # Preparar el multipart-form para la API de Jules
    files = {
        "manifest": (mission_file, open(condor_path, "rb"), "text/plain"),
        "payload": (payload_zip, open(payload_path, "rb"), "application/zip")
    }
    
    headers = {
        "Authorization": f"Bearer {JULES_API_KEY}",
        "X-Gahenax-Signature": "Hodge-Rigidity-v4"
    }

    try:
        print(f"[INFO] Conectando con Patung Gateway...")
        
        response = requests.post(JULES_API_ENDPOINT, files=files, headers=headers, timeout=60)
        response.raise_for_status()
        
        server_data = response.json()
        order_id = server_data.get("order_id", "JULES-AUTO-ID")
        
        log_event(f"Misión {mission_file} DESPACHADA con éxito. OrderID: {order_id}")
        log_event(f"Respuesta Servidor: {json.dumps(server_data)}")
        
        return order_id

    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" | Salida: {e.response.text}"
        log_event(f"FALLO en el despacho a Jules: {error_msg}")
        return None

if __name__ == "__main__":
    # Iniciar Despliegue de la Wave 3
    deploy_mission("jules_m136m_140m.condor", "jules_wave3_payload.zip")
