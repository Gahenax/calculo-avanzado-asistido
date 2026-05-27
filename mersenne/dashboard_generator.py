#!/usr/bin/env python3
"""
GAHENAX INTERCEPTOR DASHBOARD GENERATOR v3.0
============================================
Visualizes Spectral Analytics for Mersenne Search.
Generates histograms and performance maps.
"""

import polars as pl
import plotly.express as px
import plotly.graph_objects as go
import argparse
from pathlib import Path

def generate_dashboard(telemetry_dir: str, output_img: str = "interceptor_dashboard.png"):
    telemetry_dir = Path(telemetry_dir)
    files = list(telemetry_dir.glob("block_telemetry_*.jsonl"))
    
    if not files:
        print("No data to plot.")
        return
    
    dfs = [pl.read_ndjson(f) for f in files]
    df = pl.concat(dfs).to_pandas()  # Plotly prefers pandas for some complex plots
    
    # 1. Histogram of Spectral Scores
    fig1 = px.histogram(
        df, x="spectral_score", color="action",
        title="Distribución de Resonancia Espectral (GQRF)",
        labels={"spectral_score": "Spectral Score (Quantum Resonance)", "count": "Frecuencia"},
        color_discrete_map={
            "PRIME": "#00FF00", 
            "ANOMALY_COMPOSITE": "#FFA500", 
            "SPECTRAL_LOW_PRIORITY": "#888888"
        },
        marginal="box"
    )
    fig1.update_layout(template="plotly_dark")
    
    # 2. Performance: Exponent vs Time
    fig2 = px.scatter(
        df, x="p", y="wall_time_ms", color="action",
        title="Rendimiento del Motor LL (p vs Latencia)",
        labels={"p": "Exponente Mersenne (p)", "wall_time_ms": "Tiempo LL (ms)"},
        opacity=0.6
    )
    fig2.update_layout(template="plotly_dark")
    
    # Export as HTML for interactive viewing
    html_out = output_img.replace(".png", ".html").replace(".jpg", ".html")
    fig1.write_html(html_out)
    
    # Try to export as static image if kaleido is working
    try:
        fig1.write_image(output_img)
        print(f"Dashboard image saved to {output_img}")
    except Exception as e:
        print(f"Image export failed (Normal on some environments): {e}")
        print(f"Interactive dashboard saved to {html_out}")

def main():
    parser = argparse.ArgumentParser(description="Interceptor Dashboard Generator v3.0")
    parser.add_argument("--dir", default="results/mersenne/domino_wave/", help="Telemetry directory")
    parser.add_argument("--out", default="interceptor_dashboard.png", help="Output image")
    args = parser.parse_args()
    
    generate_dashboard(args.dir, args.out)

if __name__ == "__main__":
    main()
