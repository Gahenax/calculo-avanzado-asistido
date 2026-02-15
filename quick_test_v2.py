import sys
import os
import numpy as np
import time

# Ensure core is reachable
sys.path.append(os.path.join(os.getcwd(), "core"))

from GAHENAX_UA_ENGINE_V2 import ua_engine_v2

def quick_test():
    dim = 10
    seed = 42
    rng = np.random.default_rng(seed)
    # Simple lattice
    basis = rng.integers(-50, 50, (dim, dim)).astype(np.float64)
    for i in range(dim):
        basis[i, i] = 1000.0
    
    print(f"Starting UA Engine V2 Test - Dim {dim}...")
    t0 = time.time()
    coeffs, log = ua_engine_v2(basis, seed=seed, ua_budget=5000)
    dt = time.time() - t0
    
    print(f"Test Completed in {dt:.2f}s")
    print(f"Status: {log.get('stop_reason')}")
    print(f"UA Spent: {log.get('UA_spent')}")
    print(f"Min Norm2: {log.get('BB_min_norm2')}")
    print(f"Kick Rate: {log.get('kick_rate_A', 0) * 100:.1f}%")

if __name__ == "__main__":
    quick_test()
