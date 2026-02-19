---
name: universal-numerical-probe
description: Generalized adaptive mining and singularity discovery engine for any numerical function f(x).
---

# Universal Numerical Probe Skill (Kernel Drill)

This skill is a generalized version of the Riemann Rescue mission. It is designed to find roots, singularities, or phase transitions in any numerical function $f(x)$ using an adaptive precision pipeline.

## 🛠 Capabilities

1.  **Kernel Drill**: Search for singularities in any user-defined function object.
2.  **Adaptive Scanning (Alpha-Policy)**: Dynamically adjust the scanning step based on local signal complexity.
3.  **Audit Engine**: Statistical validation of findings against expected local density models.
4.  **Metrological Traceability**: Detailed logging of refinement steps (Newton vs Bisection), precision (DPS), and convergence rates.

## 📂 Structure

- `scripts/probe_core.py`: The generalized "Explore/Focus/Verify" loop.
- `scripts/stat_auditor.py`: Statistical gate for non-asymptotic density discovery.

## 🚀 Usage

```python
# Create a probe for a custom kernel (e.g., Gamma, L-functions)
from scripts.probe_core import NumericalProbe

def my_kernel(x):
    return complex_function_logic(x)

probe = NumericalProbe(kernel=my_kernel, range=[10, 100], alpha=0.1)
report = probe.run_mission(dps=80)
```

## ⚖️ Success Criteria
- **Convergence**: Roots found within specified `tol`.
- **Integrity**: Findings verified by a secondary auditor or density model.
- **Robustness**: Structural stability under parameter stress.
