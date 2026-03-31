# Device Transpile: QPanda3 vs Qiskit Benchmark Comparison

## Setup

- **Qiskit version**: 2.3.1 (`optimization_level=2`)
- **QPanda3 version**: 0.3.4 (`optimization_level=2`)
- **Backend**: FakeTorino (133-qubit IBM Heron, heavy-hex topology)
- **Qiskit Adaptive**: Circuit-aware pass manager selection (see Strategies below)
- **Basis gates**: Qiskit: cz, id, rz, sx, x | QPanda3: CZ, RZ, X1
- **Platform**: Linux x86_64, Intel Xeon Sapphire Rapids 160 vCPUs, Python 3.11.11
- **Measurement**: Runs executed sequentially (no overlap) for clean measurements

## Results

| Circuit | Strategy | QPanda3 Time | Qiskit Default Time | Qiskit Adaptive Time | QPanda3 2Q Gates | Qiskit Default 2Q Gates | Qiskit Adaptive 2Q Gates | QPanda3 2Q Depth | Qiskit Default 2Q Depth | Qiskit Adaptive 2Q Depth |
|---------|----------|-------------|--------------------|--------------------|-----------------|------------------------|------------------------|-----------------|------------------------|------------------------|
| BVlike | star | 6.3ms | 3.6ms | 6.6ms | 0 | 0 | 0 | 0 | 0 | 0 |
| BV_100 | star | 12.7ms | 51.5ms | 56.0ms | 554 | 519 | 501 | 372 | 404 | 393 |
| circSU2_100 | parameterized | 18.8ms | 59.7ms | 61.9ms | 716 | 300 | 300 | 594 | 300 | 300 |
| sq_heisenberg_100 | default | 42.2ms | 80.9ms | 76.7ms | 2,139 | 1,455 | 1,386 | 504 | 387 | 318 |
| QAOA_100 | default | 61.0ms | 217.7ms | 212.7ms | 9,592 | 8,358 | 8,499 | 1,836 | 1,432 | 1,796 |
| QFT_100 | default | 135.4ms | 372.6ms | 379.0ms | 14,040 | 12,194 | 11,970 | 3,364 | 2,899 | 2,978 |
| **clifford_100** | **clifford** | 454.5ms | 1,341.4ms | **651.7ms** | 68,747 | 65,685 | **28,368** | 19,348 | 19,817 | **657** |
| QV_100 | default | 795.0ms | 2,434.0ms | 2,504.8ms | 104,244 | 97,431 | 97,377 | 14,385 | 9,789 | 10,203 |
| **circSU2_89** | **parameterized** | 17.2ms | 2,791.6ms | **127.9ms** | 637 | 354 | 342 | 533 | 348 | 330 |
| **Total** | | **1.54s** | **7.35s** | **4.08s** | | | | | | |

### Key Observations

1. **Compilation speed**: QPanda3 is 4.8x faster than Qiskit default, 2.6x faster than Qiskit adaptive.
2. **Gate quality**: Qiskit produces fewer 2Q gates in **every circuit** — 4% to 58% fewer than QPanda3. Qiskit adaptive further improves clifford_100 by 57% (28,368 vs 65,685 default, vs 68,747 QPanda3).
3. **2Q depth**: Qiskit generally produces lower 2Q depth, especially dramatic for clifford_100 (657 adaptive vs 19,348 QPanda3).
4. **Biggest adaptive wins**: clifford_100 (2.1x faster, 57% fewer gates) and circSU2_89 (21.8x faster via reduced VF2 call limit).
5. **QPanda3 tradeoff**: Faster compilation but worse gate quality. For NISQ devices where gate errors dominate, Qiskit's lower gate count means higher circuit fidelity.

## QV_100 Profiling

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

### Why the gap depends on hardware

On macOS ARM64 (8-12 cores), QPanda3 appeared ~200x faster on QV_100. On the
160-core server, the gap narrows to 3.1x. Qiskit's Rust SABRE routing runs
multi-threaded layout trials that scale with core count. QPanda3 is
single-threaded C++ — it doesn't benefit from more cores and is actually slower
on the server due to lower single-core frequency (Xeon vs Apple Silicon).

## Adaptive Strategies

### 1. `clifford` — Topology-aware Clifford resynthesis

**Applied to**: Circuits with only Clifford gates (h, s, cx, swap, etc.) and high 2Q gate density (>10 per qubit).

**What it does**: Before the standard transpilation pipeline:
1. `CollectCliffords` — re-collects primitive Clifford gates into large Clifford operator blocks
2. `HighLevelSynthesis(hls_config=HLSConfig(clifford=["lnn"]))` — resynthesizes each block using Bravyi-Maslov LNN (Linear Nearest Neighbor) decomposition
3. `.decompose(reps=1)` — expands the 7-layer composite blocks into cx + u primitives

**Why it works**: The default `synth_clifford_greedy` produces ~5,100 CX with all-to-all connectivity. SABRE must insert SWAPs to route on heavy-hex, inflating to 65,284 CZ (12.8x overhead). LNN synthesis produces ~29,600 CX but all between adjacent virtual qubits. SabreLayout maps the linear chain to a path in the device with near-zero SWAP overhead, yielding 28,368 CZ.

```python
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes.optimization.collect_cliffords import CollectCliffords
from qiskit.transpiler.passes.synthesis.high_level_synthesis import HLSConfig, HighLevelSynthesis

hls_config = HLSConfig(clifford=["lnn"])
pre_pm = PassManager([CollectCliffords(), HighLevelSynthesis(hls_config=hls_config)])
circuit = pre_pm.run(circuit).decompose(reps=1)
pm = generate_preset_pass_manager(2, backend)
result = pm.run(circuit)
```

### 2. `parameterized` — Reduce VF2Layout call limit

**Applied to**: Circuits with unbound parameters (e.g., EfficientSU2, variational ansatze).

**What it does**: Reduces VF2Layout's `call_limit` from `(5_000_000, 10_000)` to `(100_000, 500)`.

**Why it works**: VF2Layout exhausts ~98s on circuits where it cannot find a subgraph isomorphism (e.g. 89Q circular entanglement on 133Q heavy-hex). Reducing the call limit lets VF2 succeed quickly when it can (~2s for 100Q) while failing fast when it can't (~0.1s for 89Q on server), preserving gate quality.

```python
from qiskit.transpiler.passes import VF2Layout

pm = generate_preset_pass_manager(2, backend)
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

```python
pm = generate_preset_pass_manager(2, backend)
pm.pre_init = PassManager([StarPreRouting()])
result = pm.run(circuit)
```

### 4. `default` — Standard Qiskit level 2

**Applied to**: All other circuits (QFT, QV, QAOA, Heisenberg, etc.).

## Circuit Classification Logic

```python
def classify(circuit):
    if circuit.num_parameters > 0:
        return "parameterized"
    if no_non_clifford_gates and (total_2q / num_qubits > 10):
        return "clifford"
    if max_qubit_2q_count > 0.6 * total_2q:
        return "star"
    return "default"
```

## Known Issues

- **circSU2_89 (Qiskit)**: Reduced VF2 call limit adds ~0.1s overhead on the server (VF2 tries briefly then fails). On Mac this is ~3s due to fewer cores. Tradeoff: v1 (skip VF2 entirely) was faster but had +12% gate regression on circSU2_100.
- **QPanda3 gate quality**: QPanda3 produces 4-58% more 2Q gates than Qiskit across all circuits, suggesting less aggressive optimization or a simpler routing algorithm.

## Files

- `benchpress/qiskit_gym/device_transpile/test_summit.py` — Qiskit baseline (unmodified default)
- `benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py` — Qiskit adaptive pass manager
- `benchpress/qpanda_gym/device_transpile/test_summit.py` — QPanda3 baseline
- `.benchmarks/Linux-CPython-3.11-64bit/0004_server_qpanda_clean.json` — QPanda3 server results
- `.benchmarks/Linux-CPython-3.11-64bit/0005_server_qiskit_baseline_clean.json` — Qiskit server baseline results
- `.benchmarks/Linux-CPython-3.11-64bit/0006_server_qiskit_adaptive.json` — Qiskit server adaptive results
