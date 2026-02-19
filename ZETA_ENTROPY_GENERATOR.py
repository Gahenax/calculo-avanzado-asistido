import json
import numpy as np
import os

def generate_zeta_entropy_pool():
    path = "c:/Users/USUARIO/OneDrive/Desktop/Tesis/CALCULO 3/ALL_ZEROS_FINAL.json"
    if not os.path.exists(path):
        print("Error: ALL_ZEROS_FINAL.json no encontrado.")
        return

    with open(path, "r") as f:
        data = json.load(f)
        zeros = np.array(data["zeros"])

    # Calcular espaciados
    spacings = np.diff(zeros)
    
    # Normalizar espaciados para obtener una distribución "Zeta-Chaos"
    # Usamos la fase phi = (spacing % mean_spacing) / mean_spacing
    mean_gap = np.mean(spacings)
    zeta_entropy = (spacings / mean_gap) % 1.0
    
    output_path = "c:/Users/USUARIO/.gemini/antigravity/playground/TRIKSTER-ORACLE/backend/app/core/zeta_entropy.json"
    with open(output_path, "w") as f:
        json.dump({
            "source": "Riemann Zeros T=[14, 1831]",
            "n_samples": len(zeta_entropy),
            "entropy_pool": zeta_entropy.tolist(),
            "r_mean": float(np.mean(np.minimum(spacings[:-1], spacings[1:]) / np.maximum(spacings[:-1], spacings[1:])))
        }, f, indent=2)
    
    print(f"Zeta Entropy Pool generado con {len(zeta_entropy)} muestras.")
    print(f"Ubicación: {output_path}")

if __name__ == "__main__":
    generate_zeta_entropy_pool()
