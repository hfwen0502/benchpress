# Qiskit Transpiler Enhancement Opportunities

## 1. Profiling Summary

**Test case**: QV_100 on FakeTorino (133Q heavy-hex), optimization level 2, Qiskit 2.3.1.

| Component | Time (s) | % of Total | Implementation |
|-----------|----------|-----------|----------------|
| SABRE layout + routing | 82.0 | 69% | Rust (rayon parallel) |
| consolidate_blocks | 11.7 | 10% | Rust |
| unitary_synthesis | 11.0 | 9% | Rust |
| commutative_cancellation | 4.2 | 4% | Rust |
| optimize_1q_decomposition | 3.5 | 3% | Rust |
| basis_translator | 2.1 | 2% | Rust |
| depth_analysis | 1.5 | 1% | Rust |
| Python dispatch overhead | ~2.0 | <2% | Python |
| **Total** | **~118** | | |

**Key finding**: Every transpiler pass is already implemented in Rust. Python overhead is <2% — the interpreter is essentially a dispatch layer. There are no Python-level matrix operations or hot loops to accelerate with HPC libraries. The bottleneck is algorithmic, not linguistic.

## 2. Architecture Overview

Qiskit 2.3.1's transpiler architecture:

- **Pass Manager** (Python): Orchestrates pass ordering, manages staged pipeline (init → layout → routing → translation → optimization → scheduling). Each stage is a `PassManager` that can be replaced.
- **Individual Passes** (Rust via PyO3): All compute-heavy passes (`SabreSwap`, `SabreLayout`, `CommutativeCancellation`, `ConsolidateBlocks`, `UnitarySynthesis`, `Optimize1qGatesDecomposition`) are Rust with Python wrappers.
- **SABRE** (Rust + rayon): The dominant cost. Runs `num_layout_trials × num_swap_trials` independent trials in parallel (20×20 = 400 at level 2, each with 2 forward-backward iterations). Layout trials and swap trials use mutually exclusive parallelism — layout trials parallelize across threads, each running swap trials sequentially.
- **DAGCircuit** (Rust): The circuit IR. Passes traverse/modify this directed acyclic graph. Each pass that reads the full circuit incurs O(n) traversal cost.

## 3. Completed Optimizations (Configuration-Level)

These require no Qiskit source changes — only pass manager configuration.

### Fix #1: Skip Layout/Routing on All-to-All

On fully-connected topology, routing is unnecessary — every qubit connects to every other. Yet the default pass manager still runs VF2Layout and SabreSwap.

```python
pm = generate_preset_pass_manager(optimization_level=2, backend=backend)
pm.layout = None
pm.routing = None
```

**Results**: Up to 67x speedup (bv_n280), identical gate output. Total Large all-to-all: 84.8s → 72.4s. BV circuits benefit most because VF2Layout spends significant time on subgraph isomorphism search on fully-connected graphs.

### Fix #2: Chain Pre-Layout for Heavy-Hex

Chain circuits (cat, ghz, wstate, ising) have 2Q gates between consecutive virtual qubits. On heavy-hex at 200+ qubits, SABRE produces 8-10x gate overhead because it starts from a random layout and must insert thousands of SWAPs.

The fix: detect chain structure (>75% of 2Q gates between q[i] and q[i±1]), find a long path along the heavy-hex backbone, and inject a `SetLayout` mapping virtual qubit i → physical node path[i].

```python
if _is_chain_circuit(circuit):
    path = _find_long_path(backend.coupling_map, circuit.num_qubits)
    pm.layout = PassManager([
        SetLayout(path[:circuit.num_qubits]),
        FullAncillaAllocation(coupling_map),
        EnlargeWithAncilla(),
        ApplyLayout(),
    ])
```

**Results**:

| Circuit | Qubits | Default 2Q | Adaptive 2Q | Reduction | Speedup |
|---------|--------|-----------|------------|-----------|---------|
| cat_n260 | 260 | 2,194 | 614 | 72% | 87x |
| ghz_state_n255 | 255 | 2,020 | 525 | 74% | 84x |
| wstate_n380 | 380 | 7,249 | 2,678 | 63% | 46x |
| ising_n98 | 98 | 567 | 245 | 57% | 69x |

**Why it works**: The problem is layout, not routing. With the right initial placement along the backbone, SABRE needs almost no SWAPs. Without it, SABRE solves a hard combinatorial problem from a random starting point, and greedy choices cascade at scale.

---

## 4. Investigated but No Improvement

We prototyped several additional ideas. None yielded measurable improvement:

- **Fuse cancellation passes**: `RemoveDiagonalGatesBeforeMeasure`, `RemoveIdentityEquivalent`, and `InverseCancellation` already run as a Rust-accelerated parallel batch in the init stage. Nothing to fuse.
- **General backbone layout for non-chain circuits**: Injecting a backbone layout on heavy-hex for non-chain circuits (multiply_n13, qft_n18) produces *worse* results (up to 1.84x more gates). SABRE's VF2Layout + random trials find better mappings on the full graph for non-chain structures. Backbone injection should remain targeted to chain circuits only.
- **SABRE trial count tuning**: Sweeping trials (5, 10, 20, 40, 80) on QV_20/FakeTorino shows the quality curve has a knee at ~20 — the default. Going to 80 trials saves <0.4% gates but costs 5x more time.
- **Redundant Depth/Size computation**: The optimization loop seeds `FixedPoint` with a pre-loop Depth/Size check. Removing it would save ~1% — too small to justify a change.

---

## 5. Qiskit Core Enhancements (Longer-Term)

These require modifying Qiskit's Rust source code or transpiler architecture. They cannot be prototyped from the outside.

### 5.1 Incremental Extended Set Updates in SABRE

During routing, SABRE maintains an "extended set" of upcoming gates to improve swap scoring. This set is rebuilt from scratch every routing step (`route.rs` line 910-912), even though most steps only add/remove a few gates. This is an acknowledged TODO in the Qiskit codebase.

**Expected impact**: SABRE routing is 69% of total time. If extended set computation is 10% of routing time, incremental updates could save ~7% overall.

### 5.2 Circuit-Structure-Aware SABRE Scoring

SABRE's heuristic scores SWAP candidates based on distance to the next few gates. It treats all circuits identically — no exploitation of chain, star, or cluster structure. Our Fix #2 shows 57-74% gate reduction by exploiting chain structure *before* SABRE; doing this *inside* SABRE's scoring function could generalize to other structure types without requiring pre-classification.

**Expected impact**: Potentially large for structured circuits. Risk of regression on unstructured circuits.

### 5.3 Compute-Then-Apply Refactoring (Done)

Refactored [`Optimize1qGatesDecomposition`](https://github.com/hfwen0502/qiskit/blob/fdd061ef6/crates/transpiler/src/passes/optimize_1q_gates_decomposition.rs), [`CommutationAnalysis`](https://github.com/hfwen0502/qiskit/blob/c5228537e/crates/transpiler/src/passes/commutation_analysis.rs), and [`ConsolidateBlocks`](https://github.com/hfwen0502/qiskit/blob/ea4abc77c/crates/transpiler/src/passes/consolidate_blocks.rs)
to separate read-only computation from DAG mutation. The original code interleaved reads
and writes; the refactored code batches all reads first, then applies all mutations.
This improves CPU cache behavior on the DAG's graph data structure.

Also added rayon parallelism (ready for future large circuits, but not the source of
current gains).

**Result**: 15-30% speedup on 50-100 qubit circuits, confirmed on both local Mac and
remote 160-vCPU server. Speedup is identical with rayon on or off — the gain comes
from memory access patterns, not threading.

**Details**: See [`investigation/parallel_optimization_passes.md`](https://github.com/hfwen0502/qiskit/blob/parallel-optimization-passes/investigation/parallel_optimization_passes.md) in the Qiskit fork,
branch [`parallel-optimization-passes`](https://github.com/hfwen0502/qiskit/tree/parallel-optimization-passes)
([full diff](https://github.com/hfwen0502/qiskit/compare/03c640f73...ea4abc77c)).

### 5.4 BLAS Backend for Large Unitary Operations

Qiskit's Rust code uses pure-Rust linear algebra (ndarray, nalgebra). The `blas` feature flag is not enabled. For `UnitarySynthesis` and `ConsolidateBlocks`, BLAS (OpenBLAS/MKL) could accelerate matrix operations on larger unitary blocks.

**Expected impact**: Limited for typical 1-4 qubit gate transpilation (4×4 to 16×16 matrices). Potentially significant for circuits with larger unitary blocks.

---

## 6. Summary

| # | Enhancement | Status | Impact |
|---|-------------|--------|--------|
| 1 | Skip layout/routing on all-to-all | **Done** | Up to 67x speed, identical gates |
| 2 | Chain pre-layout for heavy-hex | **Done** | 57-74% fewer gates, up to 87x speed |
| 3 | Fuse cancellation passes | No improvement | Already Rust + batched |
| 4 | Backbone layout for non-chain | No improvement | Hurts non-chain circuits |
| 5 | SABRE trial count tuning | No improvement | Default 20 already near-optimal |
| 6 | Redundant Depth/Size removal | No improvement | ~1%, too small |
| 7 | Incremental SABRE extended set | Requires Rust changes | ~7% time savings |
| 8 | Structure-aware SABRE scoring | Requires Rust changes | Potentially large |
| 9 | Compute-then-apply refactoring | **Done** (Qiskit fork) | 15-30% on large circuits |
| 10 | BLAS backend for unitaries | Requires build changes | Small for typical circuits |

## Files

- `benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py` — Device transpile adaptive strategies
- `benchpress/qiskit_gym/abstract_transpile/test_qasmbench_adaptive.py` — Abstract transpile adaptive strategies (Fix #1, Fix #2)
- `results/abstract_transpile_comparison.md` — Abstract transpile benchmark report
- `results/device_transpile_comparison.md` — Device transpile benchmark report
- `results/plot_abstract_comparison.py` — Figure generation script
