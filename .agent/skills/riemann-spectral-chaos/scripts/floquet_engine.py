import numpy as np
from scipy.linalg import eigvals

def build_floquet_ising(L: int, J: float, g: float, W: float) -> np.ndarray:
    """Builds the Floquet operator for a disordered kicked Ising chain."""
    sx = np.array([[0, 1], [1, 0]], dtype=complex)
    sz = np.array([[1, 0], [0, -1]], dtype=complex)
    id2 = np.eye(2, dtype=complex)
    
    # 1. Random fields h_j in [-W, W]
    h_list = np.random.uniform(-W, W, L)
    
    # 2. Build diagonal H_ising in Z-basis
    # We can represent the state as an integer 0..2^L-1
    diag_h = np.zeros(2**L)
    for state in range(2**L):
        energy = 0.0
        # Bits of state represent spins
        spins = [(1 if (state & (1 << j)) else -1) for j in range(L)]
        
        # Interaction J * sz_j * sz_{j+1}
        for j in range(L):
            energy += J * spins[j] * spins[(j+1)%L]
            energy += h_list[j] * spins[j]
        diag_h[state] = energy
    
    U_ising = np.diag(np.exp(-1j * diag_h))
    
    # 3. Kicked part: Prod exp(-i g sx_j)
    u_kick_local = np.cos(g) * np.eye(2) - 1j * np.sin(g) * sx
    U_kick = u_kick_local
    for _ in range(L - 1):
        U_kick = np.kron(U_kick, u_kick_local)
        
    return U_kick @ U_ising

def get_floquet_phases(U: np.ndarray) -> np.ndarray:
    """Returns the eigenphases of a unitary operator."""
    ev = eigvals(U)
    return np.angle(ev)
