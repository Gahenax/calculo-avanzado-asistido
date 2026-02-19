import math
import mpmath as mp
from typing import Callable, Optional, Dict, Any, Tuple

def hardy_z(t_val: float, dps: int = 60) -> float:
    """Calculates the real-valued Hardy Z-function at t."""
    mp.mp.dps = dps
    t = mp.mpf(t_val)
    theta = mp.siegeltheta(t)
    z = mp.exp(1j * theta) * mp.zeta(0.5 + 1j * t)
    return float(mp.re(z))

def brent_root(f: Callable[[float], float], a: float, b: float, tol: float = 1e-12) -> Dict[str, Any]:
    """Brent's method for root finding."""
    fa, fb = f(a), f(b)
    if fa * fb > 0: return {"converged": False}
    try:
        root = mp.findroot(f, (a, b), solver='brent', tol=tol)
        return {"converged": True, "root": float(root), "f_val": float(f(float(root)))}
    except:
        return {"converged": False}

def try_bracket_and_confirm(f: Callable[[float], float], t0: float, step: float, expand: int = 8) -> Dict[str, Any]:
    """Tries to find a sign change around t0 and refine the root."""
    fz0 = f(t0)
    for k in range(1, expand + 1):
        for side in [-1, 1]:
            t_edge = t0 + side * k * (step / 2.0)
            fz_edge = f(t_edge)
            if fz0 * fz_edge <= 0:
                res = brent_root(f, min(t0, t_edge), max(t0, t_edge))
                if res["converged"]:
                    return {"status": "CONFIRMED", "t_root": res["root"], "f_val": res["f_val"]}
    return {"status": "VALLEY_ONLY"}

def n_riemann_von_mangoldt(t: float) -> float:
    """Theoretical cumulative number of zeros up to t."""
    if t < 10: return 0 # Formula not accurate for very small t
    return (t / (2 * math.pi)) * (math.log(t / (2 * math.pi)) - 1) + 7/8

def get_mean_spacing(t: float) -> float:
    """Theoretical mean spacing Delta(T) at height T."""
    if t < 2*math.pi: return 1.0
    return (2 * math.pi) / math.log(t / (2 * math.pi))

def get_adaptive_step(t: float, alpha: float = 0.2) -> float:
    """Calculates adaptive scan step h(T) = alpha * Delta(T)."""
    return alpha * get_mean_spacing(t)

def gram_point(n: int) -> float:
    """Approximate n-th Gram point (where theta(t) = n*pi)."""
    # Inverse of theta(t) approx
    def theta_approx(t):
        return (t/2)*math.log(t/(2*math.pi*math.e)) - math.pi/8
    
    # Rough inversion for seed
    t = 2 * math.pi * math.exp(1) * math.exp(2 * n / 2) # Very rough
    # Refine if needed via Newton, but often 2pi * exp(W( (n+1/8)/e ))
    # For now, let's use the property that near g_n, N(g_n) approx n+1
    return t # Placeholder for logic refinement if used
