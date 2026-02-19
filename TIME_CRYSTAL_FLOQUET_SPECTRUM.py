import numpy as np
import json
import time
import os
from scipy.linalg import eigvals

def get_pauli():
    sx = np.array([[0, 1], [1, 0]], dtype=complex)
    sz = np.array([[1, 0], [0, -1]], dtype=complex)
    id2 = np.eye(2, dtype=complex)
    return sx, sz, id2

def build_h_ising(L, J, h_list, boundary='periodic'):
    sx, sz, id2 = get_pauli()
    H = np.zeros((2**L, 2**L), dtype=complex)
    
    # Interaction term
    for j in range(L):
        next_j = (j + 1) % L
        if next_j == 0 and boundary != 'periodic':
            continue
        
        # sz_j * sz_{j+1}
        op = 1
        for k in range(L):
            if k == j or k == next_j:
                op = np.kron(op, sz)
            else:
                op = np.kron(op, id2)
        H += J * op
        
    # Local field term
    for j in range(L):
        op = 1
        for k in range(L):
            if k == j:
                op = np.kron(op, sz)
            else:
                op = np.kron(op, id2)
        H += h_list[j] * op
        
    return H

def build_u_kick(L, g):
    sx, sz, id2 = get_pauli()
    # Exp(-i g * sx_total)
    # This is a product of local rotations: Prod e^{-i g sx_j}
    u_local = np.cos(g) * np.eye(2) - 1j * np.sin(g) * sx
    U = u_local
    for j in range(L - 1):
        U = np.kron(U, u_local)
    return U

def calculate_r_mean(phases):
    """phases are in [0, 2pi) or similar."""
    # Phases of Floquet operator are eigenvalues e^{i phi}
    # Sort them on the circle
    sorted_phases = np.sort(phases)
    spacings = np.diff(sorted_phases)
    # Add the wrap-around spacing
    wrap = (sorted_phases[0] + 2*np.pi) - sorted_phases[-1]
    spacings = np.append(spacings, wrap)
    
    # R-ratios for circular spacings
    r_ratios = []
    for i in range(len(spacings)):
        s1 = spacings[i]
        s2 = spacings[(i+1)%len(spacings)]
        if s1 > 1e-12 and s2 > 1e-12:
            r_ratios.append(min(s1, s2) / max(s1, s2))
    return np.mean(r_ratios)

def run_point(L, W, J, g, seeds):
    r_vals = []
    all_phases = []
    for seed in range(seeds):
        np.random.seed(seed + int(W*100) + L*1000)
        h_list = np.random.uniform(-W, W, L)
        
        H_ising = build_h_ising(L, J, h_list)
        U_ising = np.diag(np.exp(-1j * np.diag(H_ising)))
        U_kick = build_u_kick(L, g)
        U = U_kick @ U_ising
        ev = eigvals(U)
        phases = np.angle(ev)
        
        all_phases.extend(phases.tolist())
        r_mean = calculate_r_mean(phases)
        r_vals.append(r_mean)
    
    # Calculate spacings from aggregated phases
    sorted_phases = np.sort(np.array(all_phases))
    spacings = np.diff(sorted_phases)
    wrap = (sorted_phases[0] + 2*np.pi) - sorted_phases[-1]
    if wrap < 0: wrap += 2*np.pi
    spacings = np.append(spacings, wrap)
    s_norm = spacings / np.mean(spacings)

    return np.mean(r_vals), s_norm.tolist()

def main():
    L_list = [8, 9, 10]
    W_list = [0.5, 2.0, 5.0, 10.0]
    seeds = 4
    J = 1.0
    eps_frac_pi = 0.1
    g = (np.pi / 2.0) * (1.0 - eps_frac_pi)
    
    results = []
    print(f"Starting Cronos Sweep (L={L_list}, W={W_list})...")
    for L in L_list:
        for W in W_list:
            t0 = time.time()
            rm, spacings = run_point(L, W, J, g, seeds)
            dt = time.time() - t0
            print(f"L={L} W={W:5.1f} | r_mean={rm:.4f} | {dt:.1f}s")
            results.append({
                "L": L,
                "W": W,
                "r_mean": float(rm),
                "spacings": spacings,
                "is_poisson": bool(rm < 0.45),
                "is_gue": bool(rm > 0.57)
            })
            
    os.makedirs("results", exist_ok=True)
    with open("results/cronos_grid_stats.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
            
    print("Sweep complete.")

if __name__ == "__main__":
    main()
