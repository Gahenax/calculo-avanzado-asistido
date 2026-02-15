import sys
import os
import time
import math
import numpy as np

# AÃ±adir core al path
sys.path.append(os.path.join(os.getcwd(), 'core'))
from GAHENAX_UA_ENGINE_V2_HARDENED import ua_engine_v2_hardened as ua_engine_v2
try:
    from OPTIMA_CORE_SINGLEFILE import lll_reduce
except ImportError:
    lll_reduce = None

def run_quick_warfare(dim=20, seeds=[1000]):
    print("=" * 90)
    print(f"HARDENED QUICK WARFARE: DIM={dim} (P over NP)")
    print("=" * 90)
    print(f"{'Seed':>6} {'LLL norm':>12} {'UA norm':>12} {'Result':>8} {'UA_spent':>8} {'Status':>12} {'t(s)':>7}")
    
    for seed in seeds:
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

        # LLL
        B_lll, _, _, _ = lll_reduce(basis.copy(), delta=0.99)
        lll_norm = min([float(np.linalg.norm(B_lll[i].astype(np.float64))) for i in range(dim)])
        
        # UA Engine V2 Hardened
        t0 = time.time()
        coeffs, log = ua_engine_v2(basis, ua_budget=dim*dim*500, iter_max=500, seed=seed)
        t1 = time.time()
        
        v = coeffs.astype(np.float64) @ basis.astype(np.float64)
        ua_norm = float(np.linalg.norm(v))
        
        verdict = "WIN" if ua_norm < lll_norm - 1e-6 else "TIE" if abs(ua_norm - lll_norm) < 1e-6 else "LOSE"
        
        print(f"{seed:>6} {lll_norm:>12.4f} {ua_norm:>12.4f} {verdict:>8} {log['UA_spent']:>8.0f} {log['status']:>12} {t1-t0:>7.2f}")

if __name__ == "__main__":
    run_quick_warfare()
