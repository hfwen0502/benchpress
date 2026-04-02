# CLAUDE.md

## Repository Overview

Benchpress is a quantum software benchmarking suite from Qiskit. It measures compilation speed and gate quality across quantum SDKs (Qiskit, QPanda3, BQSKit, Tket, Cirq, Braket) using standardized test circuits.

Our work focuses on **comparing Qiskit vs QPanda3 transpilation** and identifying Qiskit optimization opportunities.

## Setup

No `setup.py` or `pyproject.toml` — clone and install dependencies directly.

```bash
# Core
pip install -r requirements.txt

# Qiskit benchmarks
pip install -r requirements-qiskit.txt

# QPanda3 benchmarks
pip install -r requirements-qpanda.txt
```

All SDK requirements pull a custom fork of `pytest-benchmark` with timeout-skiplist support.

## Running Tests

Run from the **repo root** (pytest.ini is at `benchpress/pytest.ini`):

```bash
# Full SDK suite
python -m pytest benchpress/qiskit_gym
python -m pytest benchpress/qpanda_gym

# Specific test category
python -m pytest benchpress/qiskit_gym/abstract_transpile
python -m pytest benchpress/qiskit_gym/device_transpile

# Filter by keyword
python -m pytest benchpress/qiskit_gym/abstract_transpile -k "large and heavy-hex"

# Save results to JSON
python -m pytest --benchmark-save=my_results benchpress/qiskit_gym/abstract_transpile
```

Results land in `.benchmarks/` (gitignored).

## Configuration

`default.conf` (repo root) controls optimization levels and basis gates:
- Qiskit: `optimization_level = 2`, basis `['id', 'sx', 'x', 'rz', 'cz']`
- QPanda3: `optimization_level = 2`
- Backend: `fake_torino` (133Q heavy-hex)
- Abstract topologies: `all-to-all`, `square`, `heavy-hex`, `linear`

Access in code via `from benchpress.config import Configuration`.

## Project Structure

```
benchpress/                     <- repo root
├── default.conf                <- global benchmark config
├── results/                    <- analysis reports, figures, prototype scripts
├── benchpress/
│   ├── config.py               <- Configuration singleton
│   ├── workouts/               <- abstract test contracts (base classes)
│   │   ├── abstract_transpile/ <- QASMBench test parametrization
│   │   └── device_transpile/   <- device-specific test contracts
│   ├── utilities/
│   │   ├── backends/           <- FlexibleBackend (topology-parameterized)
│   │   ├── io/                 <- QASM loaders, output_circuit_properties
│   │   └── validation/         <- circuit_validator
│   ├── qiskit_gym/             <- Qiskit benchmarks
│   │   ├── abstract_transpile/ <- test_qasmbench.py (baseline), test_qasmbench_adaptive.py
│   │   └── device_transpile/   <- test_summit.py (baseline), test_summit_adaptive.py
│   ├── qpanda_gym/             <- QPanda3 benchmarks (same layout)
│   └── qasm/                   <- QASMBench circuit files
│       ├── qasmbench-small/
│       ├── qasmbench-medium/
│       └── qasmbench-large/
```

## Key Pattern: Workouts

Test classes in `<sdk>_gym/` subclass abstract "workout" classes from `workouts/`. The `@benchpress_test_validation` decorator enforces that gym classes only implement methods declared in the parent workout. A `SKIPPED` status means the SDK lacks the feature.

## Our Investigation: QPanda3 vs Qiskit

Read these files for the full context of our benchmarking and optimization work:

| File | Contents |
|------|----------|
| `results/device_transpile_comparison.md` | Device transpile (FakeTorino 133Q): QPanda3 4.8x faster, Qiskit 4-58% fewer gates. Adaptive strategies: Clifford LNN resynthesis, reduced VF2Layout limits, StarPreRouting. |
| `results/abstract_transpile_comparison.md` | Abstract transpile (QASMBench, 4 topologies): QPanda3 4.5-5.6x faster. Fix #1: skip layout/routing on all-to-all (up to 67x speedup). Fix #2: chain pre-layout for heavy-hex (57-74% fewer gates, up to 87x). |
| `results/qiskit_enhancement_opportunities.md` | Profiling findings: all Qiskit passes already in Rust, SABRE is 69% of time. What we tried that didn't help (cancellation fusion, backbone layout for non-chains, trial count tuning). Rust-level opportunities that require Qiskit core changes. |

### Key Adaptive Transpile Files

- **`benchpress/qiskit_gym/abstract_transpile/test_qasmbench_adaptive.py`** — Adaptive pass manager for abstract transpile. Three strategies:
  1. All-to-all: skip layout/routing entirely (`pm.layout = None; pm.routing = None`)
  2. Heavy-hex + chain circuit: inject backbone layout via `SetLayout`
  3. Default: standard level 2

- **`benchpress/qiskit_gym/device_transpile/test_summit_adaptive.py`** — Adaptive pass manager for device transpile. Four strategies: dense Clifford (LNN resynthesis), parameterized (reduced VF2Layout call_limit), star topology (StarPreRouting), default.

### Key Technical Findings

- QPanda3 is faster but produces more 2Q gates on constrained topologies. It trades gate quality for speed.
- QPanda3 fails on circuits with `reset` gates (12/232 Large tests).
- Qiskit's SABRE router struggles with chain circuits on heavy-hex at 200+ qubits — the problem is layout, not routing. A good initial placement eliminates most SWAPs.
- All Qiskit transpiler passes are Rust-accelerated. Python overhead is <2%. No Python-level HPC acceleration opportunities exist.
- SABRE hard-codes ring heuristics only for 127/133/156-qubit IBM devices. Other sizes get random starting layouts.

## Remote Server

Benchmark runs use a Linux server (Intel Xeon Sapphire Rapids, 160 vCPUs) for clean timing:
```bash
ssh -J root@150.239.225.32 root@10.241.128.40
source /mnt/data/myenv/bin/activate
cd /mnt/data/benchpress
```
Note: remote uses `origin` as git remote name; local uses `fork`.

## Git Conventions

- Remote: `fork` → `https://github.com/hfwen0502/benchpress.git`
- Upstream: `origin` → `https://github.com/Qiskit/benchpress.git`
- Working branch: `adaptive-transpile`
- Commit style: imperative sentence, e.g. "Add chain pre-layout for heavy-hex routing"
