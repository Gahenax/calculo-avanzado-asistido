import sys
import os
import time
import numpy as np

# AÃ±adir core al path
sys.path.append(os.path.join(os.getcwd(), 'core'))
from GAHENAX_UA_ENGINE_V2 import ua_engine_v2

def debug_battle(dim=25, seed=1000, budget=62500):
    rng_ch = np.random.RandomState(seed)
    scales = np.array([1000 + 50 * i for i in range(dim)], dtype=np.int64)
    D = np.diag(scales)
    Umix = np.eye(dim, dtype=np.int64)
    for _ in range(8 * dim):
        ii = rng_ch.randint(0, dim)
        jj = rng_ch.randint(0, dim)
        if ii == jj: continue
        kk = rng_ch.randint(-3, 4)
        if kk == 0: continue
        Umix[ii] += kk * Umix[jj]
    basis = Umix @ D

    print(f"--- Battle Debug (dim={dim}, seed={seed}, budget={budget}) ---")
    t0 = time.time()
    coeffs, log = ua_engine_v2(basis, ua_budget=budget, seed=seed)
    t1 = time.time()
    
    v = coeffs.astype(np.float64) @ basis.astype(np.float64)
    norm = np.linalg.norm(v)
    
    print(f"Resulting Norm: {norm:.4f}")
    print(f"UA Spent: {log['UA_spent']}")
    print(f"Time Taken: {t1-t0:.4f}s")
    print(f"Log Details: {log}")

if __name__ == "__main__":
    debug_battle()
