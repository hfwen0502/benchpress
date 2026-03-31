# Device Transpile: Qiskit vs QPanda3 Benchmark Comparison

## Setup

- **Qiskit version**: 2.3.1 (`optimization_level=2`)
- **QPanda3 version**: 0.3.4 (`optimization_level=2`)
- **Backend**: FakeTorino (133-qubit IBM Heron, heavy-hex topology)
- **Qiskit Adaptive**: Circuit-aware pass manager selection (see Strategies below)
- **Basis gates**: Qiskit: cz, id, rz, sx, x | QPanda3: CZ, RZ, X1
- **Platforms**:
  - macOS ARM64 (Apple Silicon), Python 3.13.5
  - Linux x86_64, Intel Xeon Sapphire Rapids 160 vCPUs, Python 3.11.11

## Results — Intel Sapphire Rapids Server (160 vCPUs)

Runs executed sequentially (no overlap) for clean measurements.

| Circuit | Qiskit Default | Qiskit Adaptive | QPanda3 | Adapt vs Default | QPanda3 vs Default | Qiskit 2Q | Adaptive 2Q | QPanda3 2Q |
|---------|---------------|----------------|---------|-----------------|-------------------|-----------|------------|------------|
| BVlike | 3.6ms | 6.6ms | 6.3ms | 0.5x | 0.6x | 0 | 0 | 0 |
| BV_100 | 51.5ms | 56.0ms | 12.7ms | 0.9x | 4.1x | 519 | 501 | 554 |
| circSU2_100 | 59.7ms | 61.9ms | 18.8ms | 1.0x | 3.2x | 300 | 300 | 716 |
| sq_heisenberg_100 | 80.9ms | 76.7ms | 42.2ms | 1.1x | 1.9x | 1,455 | 1,386 | 2,139 |
| QAOA_100 | 217.7ms | 212.7ms | 61.0ms | 1.0x | 3.6x | 8,358 | 8,499 | 9,592 |
| QFT_100 | 372.6ms | 379.0ms | 135.4ms | 1.0x | 2.8x | 12,194 | 11,970 | 14,040 |
| **clifford_100** | 1,341.4ms | **651.7ms** | 454.5ms | **2.1x** | 3.0x | 65,685 | **28,368** | 68,747 |
| QV_100 | 2,434.0ms | 2,504.8ms | 795.0ms | 1.0x | 3.1x | 97,431 | 97,377 | 104,244 |
| **circSU2_89** | 2,791.6ms | **127.9ms** | 17.2ms | **21.8x** | 162.0x | 354 | 342 | 637 |
| **Total** | **7.35s** | **4.08s** | **1.54s** | **1.8x** | **4.8x** | | | |

### Key Observations (Server)

1. **Qiskit Adaptive closes the gap**: from 4.8x (default) to **2.6x** (adaptive) behind QPanda3.
2. **Qiskit produces fewer 2Q gates in every circuit** — 4% to 58% fewer than QPanda3.
3. **clifford_100**: Adaptive LNN resynthesis cuts 2Q gates from 65,685 to 28,368 (-57%), beating QPanda3's 68,747 while being only 1.4x slower.
4. **circSU2_89**: Reduced VF2 call limit cuts time from 2.79s to 0.13s (21.8x), closing the QPanda3 gap from 162x to 7.4x.
5. QPanda3 trades gate quality for compilation speed. For NISQ devices where gate errors dominate, Qiskit's lower gate count means higher circuit fidelity.

## Results — macOS ARM64 (Qiskit Adaptive vs Default)

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

## Cross-Platform Scaling

| | macOS ARM64 | Intel SPR (160 vCPUs) | Server Speedup |
|---|---|---|---|
| Qiskit QV_100 | 122.4s | 2.4s | **51x** |
| QPanda3 QV_100 | 0.53s | 0.80s | 0.7x (slower) |
| QPanda3/Qiskit ratio | 223x | 3.1x | |
| Qiskit total (9 circuits) | 347.6s | 7.35s | **47x** |
| QPanda3 total (9 circuits) | 1.04s | 1.54s | 0.7x (slower) |
| QPanda3/Qiskit ratio | 334x | 4.8x | |

**Why the gap narrows**: Qiskit's Rust SABRE routing runs multi-threaded layout
trials that scale with core count. QPanda3 is single-threaded C++ — it doesn't
benefit from more cores and is actually slower on the server due to lower
single-core frequency (Xeon vs Apple Silicon).

## QV_100 Profiling (Intel SPR Server)

### Qiskit (2.2s total)
| Component | Time | % |
|-----------|------|---|
| sabre_layout_and_routing (Rust) | 0.53s | 24% |
| unitary_synthesis (Rust) | 0.40s | 18% |
| commutative_cancellation (Rust) | 0.34s | 16% |
| consolidate_blocks (Rust) | 0.24s | 11% |
| optimize_1q_decomposition (Rust) | 0.24s | 11% |
| depth analysis | 0.13s | 6% |
| basis_translator (Rust) | 0.11s | 5% |
| Other | 0.21s | 9% |

### QPanda3 (0.78s total)
Single monolithic C++ call — no Python-visible breakdown. All routing,
optimization, and basis translation happen inside one `transpile()` call.

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

- **circSU2_89 (Qiskit)**: 4.25s on Mac vs 1.17s in v1 (which used `layout_method="sabre"`). The v2 approach keeps VF2Layout with a reduced call limit, so VF2 spends ~3s trying before falling back to SABRE. On the server this is 2.79s. This is a tradeoff: v1 was 85x faster than baseline but had +12% gate regression on circSU2_100; v2 is 23.5x faster with 0% regression on circSU2_100.
- **QPanda3 gate quality**: QPanda3 produces 4-58% more 2Q gates than Qiskit across all circuits. This suggests less aggressive optimization or a simpler routing algorithm.

## Files

- `benchpress/qiskit_gym/device_transpile/test_summit.py` — Qiskit baseline (unmodified default)
- `benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py` — Qiskit adaptive pass manager
- `benchpress/qpanda_gym/device_transpile/test_summit.py` — QPanda3 baseline
- `.benchmarks/Darwin-CPython-3.13-64bit/0003_qiskit_device_baseline.json` — Qiskit Mac baseline
- `.benchmarks/Darwin-CPython-3.13-64bit/0005_qiskit_device_adaptive.json` — Qiskit Mac adaptive v1
- `.benchmarks/Darwin-CPython-3.13-64bit/0006_0006_qiskit_device_adaptive_v2.json` — Qiskit Mac adaptive v2
- `.benchmarks/Linux-CPython-3.11-64bit/0004_server_qpanda_clean.json` — QPanda3 server results
- `.benchmarks/Linux-CPython-3.11-64bit/0005_server_qiskit_baseline_clean.json` — Qiskit server baseline results
- `.benchmarks/Linux-CPython-3.11-64bit/0006_server_qiskit_adaptive.json` — Qiskit server adaptive results
