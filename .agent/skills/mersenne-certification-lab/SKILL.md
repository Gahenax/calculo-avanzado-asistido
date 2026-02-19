---
name: mersenne-certification-lab
description: Deterministic and probabilistic certification of Mersenne primes (LL/PRP) using the Antigravity Recalibration Pack.
---

# Mersenne Certification Lab Skill

This skill enables Antigravity to operate as a high-integrity Mersenne search and verification node, transitioning from heuristic signals to deterministic number theory proofs.

## 🛠 Capabilities

1.  **Mersenne Recalibration**: Transform existing "signal lab" parameters into deterministic Mersenne job specs (Exponent `p`, Checkpoint logic).
2.  **Multistage Certification**: 
    - **P0 (Boot)**: Hardware and ALU integrity audit.
    - **P1 (Search)**: High-throughput PRP (Probabilistic) prime discovery.
    - **P2 (Verify)**: Deterministic Lucas-Lehmer (LL) certification.
3.  **Semaforo Governance**: Enforce strict evidence contracts (Residue hashes, Roundoff error < 0.40).

## 📂 Structure

- `mersenne_lab_recalibration/`: Core parameter profiles and contracts.
- `scripts/mersenne_engine_adapter.py`: Wrapper for mprime/mlucas interaction.

## 🚀 Protocolo Gahenax (Mersenne)

1.  **Ingestion**: Map `seed` to `p` using the provided recalibration mapping.
2.  **Audit**: Fail job immediately if `roundoff_error` exceeds 0.40 (RED state).
3.  **Persistence**: Checkpoints must be hashed and verified against the evidence contract.

## ⚖️ Benchmarks
- **PRP**: Probabilistic Primality (Fast).
- **LL**: Lucas-Lehmer (Deterministic Proof).
- **Correctness**: 100% Residue matching required for GREEN status.
