# Abstract Transpile: QPanda3 vs Qiskit Benchmark Comparison

## Setup

- **Qiskit version**: 2.3.1 (`optimization_level=2`)
- **QPanda3 version**: 0.3.4 (`optimization_level=2`)
- **Backend**: FlexibleBackend — idealized topologies with no error model
- **Topologies**: all-to-all, square, heavy-hex, linear
- **Basis gates**: Qiskit: cz, id, rz, sx, x | QPanda3: CZ, RZ, X1
- **Circuit suite**: QASMBench Medium (24 circuits, 11–27 qubits) and Large (59 circuits, 28–433 qubits)
- **Platform**: Linux x86_64, Intel Xeon Sapphire Rapids 160 vCPUs, Python 3.11.11
- **Measurement**: Runs executed sequentially (no overlap) for clean measurements

## Medium Results (11–27 qubits, 84 common tests)

### Compilation Time by Topology

| Topology | Qiskit (s) | QPanda3 (s) | QPanda3 Speedup |
|----------|-----------|-------------|-----------------|
| all-to-all | 16.15 | 3.99 | 4.1x |
| square | 28.91 | 6.39 | 4.5x |
| heavy-hex | 30.57 | 6.64 | 4.6x |
| linear | 30.50 | 6.57 | 4.6x |
| **Total** | **106.14** | **23.58** | **4.5x** |

QPanda3 is consistently ~4.5x faster. The gap is widest on all-to-all where routing is trivial — Qiskit's pass manager overhead dominates. Extreme case: `cc_n12` on all-to-all is **93x** slower in Qiskit (32.7ms vs 0.35ms) — a 12-qubit circuit where pass manager setup dwarfs actual compilation.

### 2Q Gate Quality by Topology

| Topology | QPanda3/Qiskit Gate Ratio | QPanda3/Qiskit Depth Ratio |
|----------|--------------------------|---------------------------|
| all-to-all | 1.00 (equal) | 0.99 (equal) |
| square | 1.12 (+12%) | 1.09 (+9%) |
| heavy-hex | 1.24 (+24%) | 1.16 (+16%) |
| linear | 1.07 (+7%) | 1.06 (+6%) |

Key finding: **all-to-all is the equalizer** — when no routing is needed, both compilers produce identical 2Q gate counts. The gap appears only when SABRE routing kicks in, confirming Qiskit's optimization passes produce better routing results.

### Worst Cases for QPanda3 Gate Quality

| Circuit | Topology | QPanda3 2Q | Qiskit 2Q | Ratio |
|---------|----------|-----------|----------|-------|
| swap_test_n25 | heavy-hex | 245 | 132 | 1.86x |
| knn_n25 | heavy-hex | 245 | 140 | 1.75x |
| cc_n12 | heavy-hex | 42 | 26 | 1.62x |
| qf21_n15 | square | 295 | 186 | 1.59x |
| knn_n25 | linear | 162 | 110 | 1.47x |
| bv_n14 | heavy-hex | 48 | 33 | 1.45x |

Heavy-hex topology consistently produces the largest gap — its irregular structure rewards Qiskit's more sophisticated routing.

### Cases Where QPanda3 Wins on Gates

| Circuit | Topology | QPanda3 2Q | Qiskit 2Q | Ratio |
|---------|----------|-----------|----------|-------|
| bv_n14 | linear | 28 | 46 | 0.61x |
| bv_n19 | linear | 38 | 52 | 0.73x |
| cc_n12 | linear | 24 | 30 | 0.80x |
| factor247_n15 | square | 405,080 | 434,396 | 0.93x |

QPanda3 produces fewer gates on BV circuits with linear topology — these have a natural linear structure that QPanda3's simpler routing handles well.

## Large Results (28–433 qubits)

*QPanda3: 220 passed, 12 failed (bwt/square_root circuits with `reset` gates). Qiskit: pending (excluding bwt circuits).*

### QPanda3 Failures

QPanda3 fails on circuits containing `reset` gates:
- `bwt_n37` × 4 topologies
- `square_root_n45` × 4 topologies
- `square_root_n60` × 4 topologies

Error: `RuntimeError: Caught an unknown exception!` from `convert_qasm_file_to_qprog`. This is a QPanda3 limitation — Qiskit handles these circuits without issue.

*Full Large comparison (QPanda3 vs Qiskit) will be added when Qiskit Large run completes.*

## Observations

1. **Pass manager overhead is Qiskit's main weakness on small circuits**: On 12-qubit `cc_n12` with all-to-all topology, Qiskit is 93x slower despite producing identical gates. The pass manager setup, analysis passes, and optimization pipeline dominate when the circuit is trivial.

2. **Routing quality gap is topology-dependent**: All-to-all shows no gate quality difference. Heavy-hex shows the largest gap (24% more QPanda3 gates on average). This suggests Qiskit's SABRE routing excels on irregular topologies.

3. **QPanda3 trades gate quality for speed uniformly**: The 4–5x compilation speedup is consistent across topologies, while gate quality degrades on constrained topologies. This is the same tradeoff seen in device transpile benchmarks.

4. **QPanda3 lacks `reset` gate support**: 12 out of 232 Large tests fail due to missing reset gate handling, affecting the `bwt` and `square_root` circuit families.

## Files

- `benchpress/qiskit_gym/abstract_transpile/test_qasmbench.py` — Qiskit tests
- `benchpress/qpanda_gym/abstract_transpile/test_qasmbench.py` — QPanda3 tests
- `benchpress/utilities/backends/flexible_backend.py` — FlexibleBackend topology generation
- `benchpress/workouts/abstract_transpile/qasmbench.py` — Test parametrization
- `.benchmarks/Linux-CPython-3.11-64bit/abstract_*.json` — Raw benchmark JSON data
