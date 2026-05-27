# Phase-3 Preregistration (RZ_MERSENNE_SPECTRAL_PHASE3_PREREG_0001)

- Version: `1.0.0`
- Created (UTC): `2026-02-23T00:00:00Z`
- Checksum (sha256 of prereg JSON sans checksum): `559984d9e4fae96b284b04348ef695fa2f690df9d0c0f61f89f80e71319a61f3`

## 1) Dataset
- Global T window: `7000.0 .. 15000.0` (span 8000)
- Target N zeros: min `10000`, ideal `12000`

### Analysis windows (frozen)
- W1: `7000.0 .. 15000.0` (span 8000)
- W2: `8000.0 .. 14000.0` (span 6000)
- W3: `9000.0 .. 13000.0` (span 4000)

## 2) Metric
- Statistic: **S(u) exponential sum over zeros (normalized)**

Definition:

```text
S(u) = sum_{gamma in window} w(gamma) * exp(i * gamma * u)
S_norm(u) = S(u) / sqrt(sum_{gamma} w(gamma)^2)

w(gamma) is a deterministic taper (kernel), evaluated over the chosen T-window.
```

Score used for classification:

```text
Given target u0, score X(u0) = |S_norm(u0)|.
Classification uses X(u0) for positives vs controls at their respective u0 values.
```

- Decision metric: **AUC (ROC) on X(u0)=|S_norm(u0)|**
- Kernels: hann, tukey

## 3) Null models
### Primary null: phase_randomization
- B: `400`
- Replace exp(i*gamma*u) with exp(i*gamma*u + i*theta_gamma), theta_gamma ~ Uniform(0, 2pi), independently per gamma. Preserves gamma distribution and window weights; destroys coherent structure.

### Secondary null (sensitivity): block_permutation
- B: `400`
- Permute contiguous blocks of gammas within coarse T-bins to preserve local density while breaking long-range alignment. Sensitivity check for window/leakage artifacts.

## 4) Evaluation sets (frozen)
### Positives: Mersenne primes with k <= 127
- ks: `[2, 3, 5, 7, 13, 17, 19, 31, 61, 89, 107, 127]`

### Controls: k where 2^k - 1 is composite (matched scale)
- ks: `[11, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71, 73]`

Notes: Controls must remain frozen. If the repository already defines a canonical control set for k<=127, replace this list once and never change again.

## 5) Gates
### Gate 0: Integrity
- Description: Dataset integrity and shard consistency checks
- PASS: All blocks pass: ordered gammas, no NaNs, no duplicates, declared ranges consistent, hashes match manifests, and global concatenation is strictly increasing.
- FAIL: Any integrity failure aborts analysis; no interpretation allowed.

### Gate 1: Sanity (positive controls)
- Description: Instrument must detect small-prime structure stably
- PASS: Detect u=log(5) and u=log(7) with z > 1.5 in at least 2 of 3 windows (W1-W3), for both kernels (hann and tukey).
- FAIL: If sanity fails, Gate 2 and Gate 3 are not interpreted; pipeline is considered uncalibrated.

### Gate 2: Primary result (Layer B)
- Description: AUC separation for Mersenne primes with k <= 127 vs controls
- PASS: AUC >= 0.65 in W1 and AUC >= 0.62 in at least one of {W2, W3}, and the 95% bootstrap CI lower bound for AUC in W1 is > 0.55.
- FAIL: AUC stays near 0.50-0.55 with no consistent elevation across windows, or high AUC in W1 collapses in W2 and W3 (instability).

### Gate 3: Layer C (2-structure audit)
- Description: Adversarial robustness check for k=10,11,29 at u = k*log(2)
- PASS: For each k in {10,11,29}, z > 2.0 appears in at least 2 of 3 windows and persists under both null models. Otherwise reported as non-robust.
- FAIL: Non-robust behavior is reported as artifact/noise; not a discovery claim.

## 6) Interpretation policy
### If Gate 2 passes
Evidence supports a weak but real spectral footprint for small Mersenne primes (k<=127) under this estimator, in the fixed T-window regime. This is not a primality certificate.

### If Gate 2 fails
The Phase-POC elevation was compatible with fluctuation; there is no robust evidence for discrimination under Phase-3 conditions.

### Forbidden claims
- This method certifies primality of 2^k - 1.
- This replaces Lucas-Lehmer or GIMPS.
- This proves the Riemann Hypothesis.
- High-u z-peaks imply Mersenne structure without robustness under nulls and windows.
