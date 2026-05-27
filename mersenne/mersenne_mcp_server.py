#!/usr/bin/env python3
"""
MERSENNE MCP SERVER
====================
Provides an interface for Gahenax agents to interact with the 
Mersenne search engine, query findings, and monitor telemetry.

Protocol: Model Context Protocol (MCP)
Author: Gahenax AI
"""

from fastmcp import FastMCP
import json
import os
from pathlib import Path
from datetime import datetime

# --- Configuración de Rutas (Gahenax v3.0) ---
BASE_DIR = Path("c:/Users/jotam/OneDrive/Desktop/GahenaxAI/OEDA_HodgeRigidity/results/mersenne")
DOMINO_DIR = BASE_DIR / "domino_wave"
LEDGER_PATH = BASE_DIR / "cert_ledger_seismic.jsonl"
LOG_PATH = BASE_DIR / "MERSENNE_OPERATIONAL_LOG.md"
GIMPS_PATH = BASE_DIR / "gimps_state.jsonl"

mcp = FastMCP("Mersenne Oracle")

@mcp.tool()
def get_status() -> str:
    """
    Retorna el estado operativo actual del motor Mersenne y la última actividad registrada.
    """
    if not LOG_PATH.exists():
        return "LOG_NOT_FOUND: El sistema está inactivo o la ruta es incorrecta."
    
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_logs = [l.strip() for l in lines if l.strip().startswith("- **")]
        current_status = "UNKNOWN"
        for line in lines:
            if "ESTADO DEL SISTEMA" in line:
                current_status = line.split(":")[-1].strip()
        
        last_event = last_logs[-1] if last_logs else "No hay eventos recientes."
    
    # Añadir info de la Wave 1 si existe
    wave1_files = list(DOMINO_DIR.glob("block_result_*.json"))
    wave_info = f"\nWave 1 Progress: {len(wave1_files)} blocks processed."
        
    return f"Status: {current_status}\nÚltimo Evento: {last_event}{wave_info}"

@mcp.tool()
def get_block_telemetry(block_id: int) -> dict:
    """
    Retorna la telemetría detallada de un bloque específico procesado por el Interceptor.
    """
    telemetry_path = DOMINO_DIR / f"block_telemetry_{block_id}.jsonl"
    if not telemetry_path.exists():
        return {"error": f"Bloque {block_id} no encontrado en domino_wave."}
    
    events = []
    with open(telemetry_path, "r", encoding="utf-8") as f:
        for line in f:
            events.append(json.loads(line))
    return {"block_id": block_id, "events": events}

@mcp.tool()
def list_certified_primes() -> list:
    """
    Retorna la lista de exponentes (p) certificados como primos de Mersenne en nuestro ledger.
    """
    findings = []
    if not LEDGER_PATH.exists():
        return []
    
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                if data.get("type") == "INVARIANCE_CERT" or data.get("status") == "SEALED":
                    findings.append(data.get("p"))
            except json.JSONDecodeError:
                continue
    return sorted(list(set(findings)))

@mcp.tool()
def get_frontier_info() -> dict:
    """
    Retorna información sobre la frontera de búsqueda actual y la integración GIMPS.
    """
    gimps_count = 0
    if GIMPS_PATH.exists():
        with open(GIMPS_PATH, "r", encoding="utf-8") as f:
            gimps_count = sum(1 for _ in f)
            
    return {
        "search_frontier": "Domino-Wave [200,000 - 500,000]",
        "core_version": "Interceptor v3.0 (Malachite FFT)",
        "gimps_sync_entries": gimps_count,
        "last_sync": datetime.fromtimestamp(os.path.getmtime(GIMPS_PATH)).isoformat() if GIMPS_PATH.exists() else "NEVER"
    }

@mcp.resource("mersenne://ledger")
def get_ledger_resource() -> str:
    """
    Provee el contenido completo del ledger de certificación sísmica.
    """
    if LEDGER_PATH.exists():
        return LEDGER_PATH.read_text(encoding="utf-8")
    return "Ledger no encontrado."

if __name__ == "__main__":
    mcp.run()
