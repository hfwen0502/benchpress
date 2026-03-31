# Device Transpile: Adaptive Pass Manager vs Qiskit Default

## Setup

- **Qiskit version**: 2.3.1
- **Backend**: FakeTorino (133-qubit IBM Heron, heavy-hex topology)
- **Baseline**: `optimization_level=2`, default pass manager
- **Adaptive**: Circuit-aware pass manager selection (see Strategies below)
- **Basis gates**: cz, id, rz, sx, x
- **Platform**: macOS ARM64, Python 3.13.5

## Results (v2 — reduced VF2 call limit for parameterized circuits)

| Circuit | Strategy | Baseline Time | Adaptive Time | Speedup | Baseline 2Q Gates | Adaptive 2Q Gates | Gate Δ | Baseline 2Q Depth | Adaptive 2Q Depth |
|---------|----------|---------------|---------------|---------|-------------------|-------------------|--------|-------------------|-------------------|
| BVlike | star | 0.08s | 0.10s | 0.8x | 0 | 0 | N/A | 0 | 0 |
| circSU2_100 | parameterized | 1.87s | 1.92s | 1.0x | 300 | 300 | 0.0% | 300 | 300 |
| BV_100 | star | 1.94s | 2.05s | 0.9x | 519 | 505 | -2.7% | 404 | 397 |
| sq_heisenberg_100 | default | 3.04s | 3.32s | 0.9x | 1,464 | 1,452 | -0.8% | 339 | 372 |
| **circSU2_89** | **parameterized** | **99.65s** | **4.25s** | **23.5x** | 354 | 342 | -3.4% | 348 | 330 |
| QAOA_100 | default | 11.60s | 11.88s | 1.0x | 8,547 | 8,349 | -2.3% | 1,725 | 1,665 |
| QFT_100 | default | 19.14s | 19.77s | 1.0x | 11,841 | 11,647 | -1.6% | 2,778 | 2,699 |
| **clifford_100** | **clifford** | **83.83s** | **17.27s** | **4.9x** | **65,284** | **28,368** | **-56.5%** | **19,783** | **657** |
| QV_100 | default | 126.48s | 122.37s | 1.0x | 97,380 | 97,827 | +0.5% | 9,909 | 10,476 |
| **Total** | | **5m48s** | **3m03s** | **1.9x** | | | | | |

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

### 2. `parameterized` — Reduce VF2Layout call limit for parameterized circuits

**Applied to**: Circuits with unbound parameters (e.g., EfficientSU2, variational ansatze).

**What it does**: Uses the default pass manager but reduces VF2Layout's `call_limit` from `(5_000_000, 10_000)` to `(100_000, 500)`.

**Why it works**: At optimization level 2, the default pipeline tries VF2Layout first (exact subgraph isomorphism). For parameterized circuits like EfficientSU2 with circular entanglement on 89 qubits, VF2Layout **cannot find an isomorphic subgraph** in FakeTorino's heavy-hex topology — it exhausts all trials (~98 seconds) before falling back to SabreLayout anyway. Reducing the call limit lets VF2 succeed quickly when it can (~2s for 100Q) while failing fast when it can't (~4s for 89Q), preserving gate quality.

**v1 approach** (skip VF2 entirely with `layout_method="sabre"`) caused a +12% gate regression on circSU2_100 because VF2PostLayout finds a better layout for 100Q. The v2 approach keeps VF2 in the pipeline with a tighter budget.

**Custom pass manager**:
```python
from qiskit.transpiler.passes import VF2Layout

pm = generate_preset_pass_manager(2, backend)
# Reduce VF2Layout call limit: try briefly, fall back to SABRE fast
for task in pm.layout._tasks:
    if isinstance(task, list):
        for item in task:
            passes = getattr(item, 'passes', None)
            if passes is not None:
                if callable(passes):
                    passes = passes()
                for p in passes:
                    if isinstance(p, VF2Layout):
                        p.call_limit = (100_000, 500)
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

- **circSU2_89**: 4.25s vs 1.17s in v1 (which used `layout_method="sabre"`). The v2 approach keeps VF2Layout with a reduced call limit, so VF2 spends ~3s trying before falling back to SABRE. This is a tradeoff: v1 was 85x faster than baseline but had +12% gate regression on circSU2_100; v2 is 23.5x faster with 0% regression on circSU2_100.
- **QV_100**: 122s, dominates the total suite time. Classified as `default` (no custom strategy). The bottleneck is routing 97K+ 2Q gates on heavy-hex topology — inherently expensive.

## Files

- `benchpress/qiskit_gym/device_transpile/test_summit.py` — Baseline (unmodified Qiskit default)
- `benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py` — Adaptive pass manager
- `.benchmarks/Darwin-CPython-3.13-64bit/0003_qiskit_device_baseline.json` — Baseline results
- `.benchmarks/Darwin-CPython-3.13-64bit/0005_qiskit_device_adaptive.json` — Adaptive v1 results (layout_method="sabre" for parameterized)
- `.benchmarks/Darwin-CPython-3.13-64bit/0006_0006_qiskit_device_adaptive_v2.json` — Adaptive v2 results (reduced VF2 call limit)
