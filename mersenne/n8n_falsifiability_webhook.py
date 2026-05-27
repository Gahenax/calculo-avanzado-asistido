import requests
import json
import socket
from datetime import datetime

# ============================================================================
# OEDA n8n/ZAPIER CHATOPS WEBHOOK - Falsifiability Ledger Notifier
# ============================================================================

def notify_falsifiability_event(experiment_name: str, status: str, details: dict, n8n_webhook_url: str = "http://localhost:5678/webhook/oeda-audit"):
    """
    Empaquetado moderno (DataOps/ChatOps) del Falsifiability Ledger.
    Envía los descubrimientos de los Loci Fantasmas de Mersenne o Riemann 
    directamente al pipeline de n8n para notificar en Slack y registrar en Jira.
    """
    payload = {
        "event_type": "FALSIFIABILITY_LEDGER_UPDATE",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "system_host": socket.gethostname(),
        "experiment": experiment_name,
        "status": status,  # e.g., "GREEN", "RED_ALERT", "LOCI_FOUND"
        "details": details
    }
    
    try:
        response = requests.post(
            n8n_webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=5
        )
        if response.status_code in [200, 201]:
            print(f"[+] Notificación MLOps/ChatOps enviada exitosamente a n8n: {status}")
        else:
            print(f"[!] n8n respondió con código de error: {response.status_code}")
    except Exception as e:
        print(f"[!] Imposible contactar al orquestador n8n (asegúrese de correr /n8n-self-hosted-deploy): {e}")

if __name__ == "__main__":
    # Test stub
    notify_falsifiability_event(
        experiment_name="MERSENNE_GHOST_LOCI_M127",
        status="RED_ALERT",
        details={
            "telemetry_variance": 0.05,
            "hodge_pcp_breach": True,
            "message": "Violación estructural detectada en la vecindad del primo M127."
        }
    )
