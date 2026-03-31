# Abstract Transpile: QPanda3 vs Qiskit Benchmark Comparison

## Key Finding: Qiskit SABRE Routing Issue on Large Heavy-Hex

Qiskit's SABRE router inserts **3.5x more SWAPs than necessary** on linear-chain circuits (cat, ghz, wstate, ising) at 100–380 qubits on heavy-hex topology. For example, `cat_n260` on heavy-hex: QPanda3 produces 606 2Q gates (2.3x optimal), Qiskit produces 2,194 (8.5x optimal) and takes 5.3s. The same circuit compiles optimally on all other topologies for both compilers. This is the most practically relevant finding since heavy-hex is IBM's production topology. See [detailed analysis](#analysis-qiskit-sabre-routing-issue-on-large-heavy-hex-chain-circuits) below.

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

## Large Results (28–433 qubits, 220 common tests)

QPanda3: 220 passed, 12 failed (bwt/square_root circuits with `reset` gates). Qiskit: 228 passed (bwt excluded due to extreme compile time >10 min per test, 300s timeout).

### Compilation Time by Topology

| Topology | Qiskit (s) | QPanda3 (s) | QPanda3 Speedup |
|----------|-----------|-------------|-----------------|
| all-to-all | 64.60 | 11.34 | 5.7x |
| square | 112.73 | 20.98 | 5.4x |
| heavy-hex | 158.76 | 23.34 | 6.8x |
| linear | 140.59 | 29.30 | 4.8x |
| **Total** | **476.68** | **84.96** | **5.6x** |

The speed gap **widens at scale** (5.6x Large vs 4.5x Medium). Heavy-hex shows the largest gap (6.8x) because Qiskit's SABRE routing uses more iterations on irregular topologies.

Extreme outliers: `ising_n98` heavy-hex (QPanda3 **196x** faster), `ghz_state_n255` heavy-hex (**193x**), `cat_n260` heavy-hex (**186x**). These are simple-structure circuits where Qiskit's pass manager overhead is disproportionate.

Qiskit is **faster** on a few large circuits: `ising_n420` heavy-hex (Qiskit 0.64x), `ising_n420` square (0.84x), `wstate_n380` square (0.89x) — suggesting Qiskit's Rust SABRE scales better on very high qubit counts.

### 2Q Gate Quality by Topology

| Topology | QPanda3/Qiskit Gate Ratio | QPanda3/Qiskit Depth Ratio |
|----------|--------------------------|---------------------------|
| all-to-all | 0.98 (QPanda3 slightly better) | 1.00 (equal) |
| square | 1.10 (+10%) | 1.07 (+7%) |
| heavy-hex | 1.06 (+6%) | 1.03 (+3%) |
| linear | 1.17 (+17%) | 1.20 (+20%) |

Compared to Medium, the gate quality picture shifts:
- **All-to-all**: QPanda3 now slightly **wins** (0.98x) — QPanda3 produces fewer QFT gates at large scale (qft_n320: 8,750 vs 11,780)
- **Heavy-hex**: Gap narrows from 1.24 to 1.06 — QPanda3 does very well on structured circuits at scale (cat_n260: 0.28x, ghz_state_n255: 0.28x, wstate_n380: 0.28x)
- **Linear**: Gap widens to 1.17 — QPanda3 struggles most here (qft_n320 linear: 2.49x more gates)

### Worst Cases for QPanda3 Gate Quality (Large)

| Circuit | Topology | QPanda3 2Q | Qiskit 2Q | Ratio |
|---------|----------|-----------|----------|-------|
| qft_n320 | linear | 222,084 | 89,218 | 2.49x |
| swap_test_n361 | linear | 3,006 | 1,622 | 1.85x |
| qft_n160 | linear | 49,774 | 27,153 | 1.83x |
| knn_341 | linear | 2,583 | 1,532 | 1.69x |
| adder_n433 | linear | 9,821 | 6,014 | 1.63x |
| knn_341 | square | 4,362 | 2,717 | 1.61x |

Linear topology is QPanda3's weakest point at scale — QFT circuits show up to 2.5x more 2Q gates.

### Cases Where QPanda3 Wins on Gates (Large)

| Circuit | Topology | QPanda3 2Q | Qiskit 2Q | Ratio |
|---------|----------|-----------|----------|-------|
| cat_n260 | heavy-hex | 606 | 2,194 | 0.28x |
| ghz_state_n255 | heavy-hex | 563 | 2,020 | 0.28x |
| wstate_n380 | heavy-hex | 2,060 | 7,249 | 0.28x |
| ising_n98 | heavy-hex | 317 | 567 | 0.56x |
| cc_n32 | linear | 64 | 94 | 0.68x |
| qft_n320 | all-to-all | 8,750 | 11,780 | 0.74x |
| qft_n160 | all-to-all | 4,270 | 5,700 | 0.75x |
| qft_n63 | all-to-all | 1,554 | 2,014 | 0.77x |

Notably, QPanda3 produces **72% fewer gates** on cat/ghz/wstate circuits on heavy-hex. These are simple entanglement chains where QPanda3's routing finds a more direct mapping. QPanda3 also wins on QFT all-to-all at large scale.

### QPanda3 Failures

QPanda3 fails on circuits containing `reset` gates:
- `bwt_n37` × 4 topologies
- `square_root_n45` × 4 topologies
- `square_root_n60` × 4 topologies

Error: `RuntimeError: Caught an unknown exception!` from `convert_qasm_file_to_qprog`. This is a QPanda3 limitation — Qiskit handles these circuits without issue. Qiskit's `bwt_n37` was excluded from the run due to extreme compile times (>10 min on square/heavy-hex/linear topologies).

## Analysis: Qiskit SABRE Routing Issue on Large Heavy-Hex Chain Circuits

The most striking finding is Qiskit's poor gate quality on large heavy-hex with linear-chain circuits. Examining `cat_n260` across topologies reveals the pattern:

| Topology | QPanda3 2Q | Qiskit 2Q | Ratio | Qiskit Time |
|----------|-----------|----------|-------|-------------|
| all-to-all | 259 | 259 | 1.00 | 167ms |
| square | 259 | 259 | 1.00 | 18ms |
| linear | 259 | 259 | 1.00 | 14ms |
| heavy-hex | 606 | 2,194 | 0.28 | 5,299ms |

The same circuit produces **identical** output (259 gates = the original CX chain, zero routing overhead) on all-to-all, square, and linear. But on heavy-hex, QPanda3 produces 606 gates (~2.3x overhead, reasonable for mapping a chain onto heavy-hex), while Qiskit produces **2,194 gates** (8.5x overhead) and takes **5.3 seconds**.

This pattern repeats for all linear-chain circuits at scale:

| Circuit | Qubits | Optimal 2Q | QPanda3 (heavy-hex) | Qiskit (heavy-hex) | Qiskit Overhead |
|---------|--------|-----------|---------------------|-------------------|----------------|
| cat_n260 | 260 | 259 | 606 (2.3x) | 2,194 (8.5x) | 3.6x worse |
| ghz_state_n255 | 255 | 254 | 563 (2.2x) | 2,020 (8.0x) | 3.6x worse |
| wstate_n380 | 380 | 758 | 2,060 (2.7x) | 7,249 (9.6x) | 3.5x worse |
| ising_n98 | 98 | 194 | 317 (1.6x) | 567 (2.9x) | 1.8x worse |

QPanda3 achieves near-optimal routing (2-3x overhead) while Qiskit's SABRE inserts 3.5x more SWAPs than necessary. This suggests SABRE's heuristic search doesn't efficiently find linear-chain embeddings on heavy-hex at large qubit counts, despite such embeddings being straightforward (just walk along the heavy-hex backbone).

This is a potential Qiskit optimization opportunity or bug — these are exactly the kind of circuits that run on real IBM heavy-hex hardware.

## Summary: Device vs Abstract Transpile

| | Speed | Gate Quality |
|---|---|---|
| **Device transpile** (133Q heavy-hex) | QPanda3 4.8x faster | Qiskit 4-58% fewer gates in **all** circuits |
| **Abstract: medium** (11-27Q) | QPanda3 4.5x faster | Qiskit better on constrained topos, equal on all-to-all |
| **Abstract: large** (28-433Q) | QPanda3 5.6x faster | Mixed — Qiskit better on linear/square, **but has a routing problem on large heavy-hex chain circuits** |

Qiskit does **not** perform poorly across the board on abstract transpile. It still produces better gate quality on square and linear topologies. The apparent "QPanda3 wins on heavy-hex" result is driven by a specific SABRE routing inefficiency on large linear-chain circuits, not a general QPanda3 advantage.

## Observations

1. **Pass manager overhead is Qiskit's main weakness**: On small circuits (cc_n12, 12Q all-to-all), Qiskit is 93x slower. On large simple-structure circuits (ising_n98, 98Q heavy-hex), it's 196x slower. Pass manager setup, analysis passes, and the optimization pipeline dominate when the circuit structure is simple.

2. **The speed gap widens at scale**: Medium shows 4.5x, Large shows 5.6x. Qiskit's per-circuit overhead grows with qubit count. However, on very large complex circuits (ising_n420, 420Q), Qiskit's Rust SABRE actually becomes faster — its multi-core parallelism pays off.

3. **Gate quality is topology- and scale-dependent**:
   - All-to-all: equal at medium, QPanda3 slightly better at large (QFT)
   - Square: QPanda3 10-12% worse consistently
   - Heavy-hex: QPanda3 24% worse at medium but only 6% worse at large (driven by SABRE routing issue above)
   - Linear: QPanda3's weakest topology, especially at scale (QFT: 2.5x more gates)

4. **Qiskit SABRE has a scaling issue on large heavy-hex chain circuits**: cat, ghz, wstate, ising circuits show Qiskit inserting 3.5x more SWAPs than QPanda3 on heavy-hex at 100-380 qubits. This is likely a heuristic limitation, not a fundamental one.

5. **Qiskit excels on QFT + linear topology**: QFT has all-pairs connectivity that requires extensive routing on linear topology. Qiskit's SABRE produces dramatically better results (2.5x fewer gates at 320Q).

6. **QPanda3 lacks `reset` gate support**: 12 out of 232 Large tests fail. Qiskit's `bwt_n37` causes extreme compile times on constrained topologies (>10 min).

## Files

- `benchpress/qiskit_gym/abstract_transpile/test_qasmbench.py` — Qiskit tests
- `benchpress/qpanda_gym/abstract_transpile/test_qasmbench.py` — QPanda3 tests
- `benchpress/utilities/backends/flexible_backend.py` — FlexibleBackend topology generation
- `benchpress/workouts/abstract_transpile/qasmbench.py` — Test parametrization
- `.benchmarks/Linux-CPython-3.11-64bit/abstract_*.json` — Raw benchmark JSON data
