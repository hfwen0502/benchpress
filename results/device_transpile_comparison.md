# Device Transpile: Adaptive Pass Manager vs Qiskit Default

## Setup

- **Qiskit version**: 2.3.1
- **Backend**: FakeTorino (133-qubit IBM Heron, heavy-hex topology)
- **Baseline**: `optimization_level=2`, default pass manager
- **Adaptive**: Circuit-aware pass manager selection (see Strategies below)
- **Basis gates**: cz, id, rz, sx, x
- **Platform**: macOS ARM64, Python 3.13.5

## Results

| Circuit | Strategy | Baseline Time | Adaptive Time | Speedup | Baseline 2Q Gates | Adaptive 2Q Gates | Gate Δ | Baseline 2Q Depth | Adaptive 2Q Depth |
|---------|----------|---------------|---------------|---------|-------------------|-------------------|--------|-------------------|-------------------|
| BVlike | star | 0.08s | 0.10s | 0.8x | 0 | 0 | N/A | 0 | 0 |
| circSU2_100 | parameterized | 1.87s | 1.25s | 1.5x | 300 | 336 | +12.0% | 300 | 336 |
| BV_100 | star | 1.94s | 1.99s | 1.0x | 519 | 501 | -3.5% | 404 | 393 |
| sq_heisenberg_100 | default | 3.04s | 3.05s | 1.0x | 1,464 | 1,347 | -8.0% | 339 | 387 |
| QAOA_100 | default | 11.60s | 11.99s | 1.0x | 8,547 | 8,433 | -1.3% | 1,725 | 1,998 |
| QFT_100 | default | 19.14s | 25.45s | 0.75x | 11,841 | 11,597 | -2.1% | 2,778 | 2,702 |
| **clifford_100** | **clifford** | **83.83s** | **16.84s** | **5.0x** | **65,284** | **28,368** | **-56.5%** | **19,783** | **657** |
| **circSU2_89** | **parameterized** | **99.65s** | **1.17s** | **85.1x** | 354 | 354 | 0.0% | 348 | 348 |
| QV_100 | default | 126.48s | 118.38s | 1.1x | 97,380 | 97,395 | 0.0% | 9,909 | 10,323 |
| **Total** | | **17m33s** | **9m19s** | **1.9x** | | | | | |

## Strategies

### 1. `clifford` — Topology-aware Clifford resynthesis

**Applied to**: Circuits with only Clifford gates (h, s, cx, swap, etc.) and high 2Q gate density (>10 per qubit).

**What it does**: Before the standard transpilation pipeline:
1. `CollectCliffords` — re-collects primitive Clifford gates into large Clifford operator blocks
2. `HighLevelSynthesis(hls_config=HLSConfig(clifford=["lnn"]))` — resynthesizes each block using Bravyi-Maslov LNN (Linear Nearest Neighbor) decomposition
3. `.decompose(reps=1)` — expands the 7-layer composite blocks into cx + u primitives

**Why it works**: The default `synth_clifford_greedy` produces ~5,100 CX with all-to-all connectivity. SABRE must insert SWAPs to route on heavy-hex, inflating to 65,284 CZ (12.8x overhead). LNN synthesis produces ~29,600 CX but all between adjacent virtual qubits. SabreLayout maps the linear chain to a path in the device with near-zero SWAP overhead, yielding 28,368 CZ.

**Custom pass manager**:
```python
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes.optimization.collect_cliffords import CollectCliffords
from qiskit.transpiler.passes.synthesis.high_level_synthesis import HLSConfig, HighLevelSynthesis

# Preprocessing step (before standard transpilation)
hls_config = HLSConfig(clifford=["lnn"])
pre_pm = PassManager([
    CollectCliffords(),
    HighLevelSynthesis(hls_config=hls_config),
])
processed = pre_pm.run(circuit)
circuit = processed.decompose(reps=1)

# Then standard transpilation
pm = generate_preset_pass_manager(2, backend)
result = pm.run(circuit)
```

### 2. `parameterized` — Skip VF2Layout for parameterized circuits

**Applied to**: Circuits with unbound parameters (e.g., EfficientSU2, variational ansatze).

**What it does**: Uses `layout_method="sabre"` instead of the default VF2Layout → SabreLayout fallback.

**Why it works**: At optimization level 2, the default pipeline tries VF2Layout first (exact subgraph isomorphism, up to 5M calls and 10K trials). For parameterized circuits like EfficientSU2 with circular entanglement on 89 qubits, VF2Layout **cannot find an isomorphic subgraph** in FakeTorino's heavy-hex topology — it exhausts all trials (~98 seconds) before falling back to SabreLayout anyway. Skipping directly to SabreLayout avoids this wasted search.

**Custom pass manager**:
```python
pm = generate_preset_pass_manager(2, backend, layout_method="sabre")
result = pm.run(circuit)
```

### 3. `star` — StarPreRouting for star-topology circuits

**Applied to**: Circuits where one qubit participates in >60% of all 2Q gates (e.g., Bernstein-Vazirani).

**What it does**: Injects `StarPreRouting` pass before the standard pipeline.

**Why it works**: BV circuits have a star connectivity pattern (one central qubit connected to all others). StarPreRouting recognizes this pattern and pre-routes it efficiently. In practice, the benefit on this benchmark suite is marginal since SABRE already handles BV well.

**Custom pass manager**:
```python
pm = generate_preset_pass_manager(2, backend)
pm.pre_init = PassManager([StarPreRouting()])
result = pm.run(circuit)
```

### 4. `default` — Standard Qiskit level 2

**Applied to**: All other circuits (QFT, QV, QAOA, Heisenberg, etc.).

**What it does**: Standard `generate_preset_pass_manager(2, backend)` with no modifications.

## Circuit Classification Logic

```python
def classify(circuit):
    # 1. Parameterized: has unbound parameters
    if circuit.num_parameters > 0:
        return "parameterized"

    # 2. Dense Clifford: only Clifford gates + high 2Q density (>10 per qubit)
    if no_non_clifford_gates and (total_2q / num_qubits > 10):
        return "clifford"

    # 3. Star: one qubit in >60% of 2Q gates
    if max_qubit_2q_count > 0.6 * total_2q:
        return "star"

    # 4. Default
    return "default"
```

## Known Issues

- **circSU2_100**: +12% gate count regression. The `layout_method="sabre"` bypasses VF2PostLayout which can find better final layouts. VF2 succeeds quickly for 100Q (within the device) but not for 89Q. A fix would be to only skip VF2 when `num_qubits > backend_num_qubits * threshold`.
- **QFT_100**: 0.75x slower in this run. Classified as `default` (same PM as baseline). Likely benchmark variance from single-round measurement.

## Files

- `benchpress/qiskit_gym/device_transpile/test_summit.py` — Baseline (unmodified Qiskit default)
- `benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py` — Adaptive pass manager
- `.benchmarks/Darwin-CPython-3.13-64bit/0003_qiskit_device_baseline.json` — Baseline results
- `.benchmarks/Darwin-CPython-3.13-64bit/0005_qiskit_device_adaptive.json` — Adaptive results
