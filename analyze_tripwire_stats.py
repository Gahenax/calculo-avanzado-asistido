import json
import numpy as np
import os
import sys

# Add skills scripts to path
sys.path.append(os.path.join(os.getcwd(), ".agent", "skills", "riemann-spectral-chaos", "scripts"))
from spectral_engine import analyze_spectrum

def main():
    path = "zeros_tripwire_highres.jsonl"
    if not os.path.exists(path):
        print("Data not found.")
        return
    
    roots = []
    with open(path, "r") as f:
        for line in f:
            data = json.loads(line)
            if data.get("event") == "zero_candidate" and data.get("accepted"):
                roots.append(data["root"])
    
    print(f"Analizing {len(roots)} roots...")
    if len(roots) < 2:
        return
        
    res = analyze_spectrum(roots)
    print(f"R-mean: {res['r_mean']:.6f}")
    
if __name__ == "__main__":
    main()
