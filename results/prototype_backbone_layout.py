"""Prototype: General backbone layout for heavy-hex.

SABRE hard-codes ring heuristics only for 127/133/156-qubit IBM devices.
For other device sizes (e.g., FlexibleBackend heavy-hex at 291Q), SABRE
falls back to random starting layouts.

This prototype injects a backbone-traced layout as SABRE's starting point
for ALL circuits on heavy-hex (not just chains), and measures whether it
improves gate quality.

Usage:
    python results/prototype_backbone_layout.py

Requires: qiskit >= 2.3, benchpress package installed
"""

import time
import json
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from qiskit import QuantumCircuit
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import (
    SetLayout,
    FullAncillaAllocation,
    EnlargeWithAncilla,
    ApplyLayout,
)
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from benchpress.utilities.backends import FlexibleBackend

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
NUM_REPEATS = int(os.getenv("NUM_REPEATS", "3"))
SEED = 12345
QUICK_MODE = os.getenv("QUICK", "0") == "1"


def _find_long_path(coupling_map, min_length):
    """Find a simple path of at least min_length on the coupling map.

    Same algorithm as Fix #2: start from degree-1 endpoints, always pick
    lowest-index unvisited neighbor to trace the heavy-hex backbone.
    """
    graph = coupling_map.graph
    if hasattr(graph, "to_undirected"):
        ugraph = graph.to_undirected()
    else:
        ugraph = graph

    nodes_by_degree = sorted(ugraph.node_indices(), key=lambda n: ugraph.degree(n))
    best_path = []

    for start in nodes_by_degree[:10]:
        path = [start]
        visited = {start}
        current = start
        while True:
            neighbors = sorted(n for n in ugraph.neighbors(current) if n not in visited)
            if not neighbors:
                break
            current = neighbors[0]
            path.append(current)
            visited.add(current)
        if len(path) > len(best_path):
            best_path = path
        if len(path) >= min_length:
            return path

    if len(best_path) < min_length:
        on_path = set(best_path)
        remaining = [n for n in ugraph.node_indices() if n not in on_path]
        best_path.extend(remaining[: min_length - len(best_path)])

    return best_path


def _make_backbone_pm(backend, num_qubits):
    """Create a pass manager with backbone layout injection."""
    path = _find_long_path(backend.coupling_map, num_qubits)
    layout = path[:num_qubits]
    pm = generate_preset_pass_manager(optimization_level=2, backend=backend)
    pm.layout = PassManager([
        SetLayout(layout),
        FullAncillaAllocation(backend.coupling_map),
        EnlargeWithAncilla(),
        ApplyLayout(),
    ])
    return pm


def load_qasm_circuits():
    """Load a selection of QASMBench circuits for testing."""
    from benchpress.config import Configuration

    circuits = {}

    # Try to load a variety of circuit types
    bench_base = os.path.join(os.path.dirname(RESULTS_DIR), "benchpress", "qasm")

    # Medium circuits (11-27 qubits) — non-chain types for interesting comparison
    medium_targets = [
        "adder_n10", "multiply_n13", "qft_n18", "qram_n20",
        "qec9xz_n17", "dnn_n16", "sat_n11",
    ]

    # Large circuits (28+ qubits) — non-chain types
    large_targets = [
        "qft_n29", "multiplier_n45", "hubbard_n52",
        "qgan_n39", "vqe_uccsd_n28",
    ]

    if QUICK_MODE:
        medium_targets = medium_targets[:3]
        large_targets = []

    for size_dir, targets in [
        ("qasmbench-medium", medium_targets),
        ("qasmbench-large", large_targets),
    ]:
        base = os.path.join(bench_base, size_dir)
        if not os.path.isdir(base):
            continue
        for name in targets:
            qasm_path = os.path.join(base, name, f"{name}.qasm")
            if os.path.exists(qasm_path):
                try:
                    qc = QuantumCircuit.from_qasm_file(qasm_path)
                    circuits[name] = qc
                except Exception as e:
                    print(f"  Skipping {name}: {e}")

    return circuits


def run_comparison():
    """Compare default vs backbone layout on heavy-hex for various circuits."""
    circuits = load_qasm_circuits()
    if not circuits:
        print("No circuits loaded. Check QASMBench path.")
        return None

    print(f"Loaded {len(circuits)} circuits\n")

    results = {}
    for name, circuit in sorted(circuits.items()):
        nq = circuit.num_qubits
        backend = FlexibleBackend(nq, "heavy-hex", control_flow=True)

        default_gates = []
        default_times = []
        backbone_gates = []
        backbone_times = []

        for rep in range(NUM_REPEATS):
            # Default
            pm_default = generate_preset_pass_manager(
                optimization_level=2, backend=backend
            )
            t0 = time.perf_counter()
            try:
                trans_default = pm_default.run(circuit)
                dt = time.perf_counter() - t0
                ops = trans_default.count_ops()
                cz = ops.get("cz", 0) + ops.get("cx", 0) + ops.get("ecr", 0)
                default_gates.append(cz)
                default_times.append(dt)
            except Exception as e:
                print(f"  {name} default failed: {e}")
                break

            # Backbone layout
            pm_backbone = _make_backbone_pm(backend, nq)
            t0 = time.perf_counter()
            try:
                trans_backbone = pm_backbone.run(circuit)
                dt = time.perf_counter() - t0
                ops = trans_backbone.count_ops()
                cz = ops.get("cz", 0) + ops.get("cx", 0) + ops.get("ecr", 0)
                backbone_gates.append(cz)
                backbone_times.append(dt)
            except Exception as e:
                print(f"  {name} backbone failed: {e}")
                break

        if default_gates and backbone_gates:
            ratio = np.mean(backbone_gates) / np.mean(default_gates)
            speedup = np.mean(default_times) / np.mean(backbone_times)
            results[name] = {
                "num_qubits": nq,
                "default_gates_mean": float(np.mean(default_gates)),
                "default_gates_min": int(np.min(default_gates)),
                "backbone_gates_mean": float(np.mean(backbone_gates)),
                "backbone_gates_min": int(np.min(backbone_gates)),
                "gate_ratio": float(ratio),
                "default_time_mean": float(np.mean(default_times)),
                "backbone_time_mean": float(np.mean(backbone_times)),
                "speedup": float(speedup),
            }
            marker = "+" if ratio < 0.95 else ("-" if ratio > 1.05 else "=")
            print(
                f"  {marker} {name:25s} ({nq:3d}Q): "
                f"default={np.mean(default_gates):.0f}, "
                f"backbone={np.mean(backbone_gates):.0f}, "
                f"ratio={ratio:.2f}, "
                f"time: {np.mean(default_times):.2f}s → {np.mean(backbone_times):.2f}s"
            )

    return results


if __name__ == "__main__":
    print("=== Backbone Layout vs Default on Heavy-Hex ===\n")
    print("Comparing default SABRE layout vs backbone-injected layout")
    print("on non-chain QASMBench circuits (heavy-hex topology)\n")

    results = run_comparison()

    if results:
        # Save raw data
        with open(os.path.join(RESULTS_DIR, "prototype_backbone_layout.json"), "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved prototype_backbone_layout.json")

        # Summary
        ratios = [r["gate_ratio"] for r in results.values()]
        improved = sum(1 for r in ratios if r < 0.95)
        worse = sum(1 for r in ratios if r > 1.05)
        neutral = len(ratios) - improved - worse

        print(f"\nSummary: {improved} improved, {neutral} neutral, {worse} worse "
              f"(out of {len(ratios)} circuits)")
        print(f"Mean gate ratio: {np.mean(ratios):.3f}")
        if improved > 0:
            best = min(results.items(), key=lambda x: x[1]["gate_ratio"])
            print(f"Best improvement: {best[0]} ({best[1]['gate_ratio']:.2f}x)")

    print("\nDone.")
