"""Prototype: SABRE trial count sweep.

Measures 2Q gate count and compilation time as a function of SABRE trial count
on representative circuits. Demonstrates whether the default 20x20 trial count
is optimal or if topology-aware trial tuning would help.

Usage:
    python results/prototype_sabre_trial_sweep.py

Requires: qiskit >= 2.3, matplotlib, numpy
"""

import time
import json
import os
import numpy as np
import matplotlib.pyplot as plt

from qiskit.circuit.library import QuantumVolume
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.transpiler.passes import SabreSwap, SabreLayout

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
TRIAL_COUNTS = [5, 10, 20, 40, 80]
NUM_REPEATS = 3  # average over multiple runs for stability
SEED = 12345
QUICK_MODE = os.getenv("QUICK", "0") == "1"  # QUICK=1 for smaller test circuits


def _patch_sabre_trials(pm, layout_trials, swap_trials):
    """Patch SabreLayout and SabreSwap trial counts in a preset pass manager."""
    # Patch layout stage — find SabreLayout instances
    if pm.layout is not None:
        for task in pm.layout._tasks:
            items = task if isinstance(task, list) else [task]
            for item in items:
                passes = getattr(item, 'passes', None)
                if passes is not None:
                    if callable(passes):
                        passes = passes()
                    for p in passes:
                        if isinstance(p, SabreLayout):
                            p.swap_trials = swap_trials
                            p.layout_trials = layout_trials

    # Patch routing stage — find SabreSwap instances
    if pm.routing is not None:
        for task in pm.routing._tasks:
            items = task if isinstance(task, list) else [task]
            for item in items:
                passes = getattr(item, 'passes', None)
                if passes is not None:
                    if callable(passes):
                        passes = passes()
                    for p in passes:
                        if isinstance(p, SabreSwap):
                            p.trials = swap_trials


def run_sweep_qv100():
    """Sweep trial counts on QV with FakeTorino."""
    from qiskit_ibm_runtime.fake_provider import FakeTorino

    backend = FakeTorino()
    qv_size = 20 if QUICK_MODE else 100
    circuit = QuantumVolume(qv_size, qv_size, seed=SEED)
    label = f"QV_{qv_size}"
    print(f"  Circuit: {label}")

    results = {}
    for trials in TRIAL_COUNTS:
        times = []
        gate_counts = []
        depths = []
        for rep in range(NUM_REPEATS):
            pm = generate_preset_pass_manager(optimization_level=2, backend=backend)
            _patch_sabre_trials(pm, layout_trials=trials, swap_trials=trials)

            t0 = time.perf_counter()
            trans_qc = pm.run(circuit)
            elapsed = time.perf_counter() - t0

            ops = trans_qc.count_ops()
            cz_count = ops.get("cz", 0) + ops.get("cx", 0) + ops.get("ecr", 0)

            times.append(elapsed)
            gate_counts.append(cz_count)

        results[trials] = {
            "time_mean": np.mean(times),
            "time_std": np.std(times),
            "gates_mean": np.mean(gate_counts),
            "gates_std": np.std(gate_counts),
            "gates_min": int(np.min(gate_counts)),
        }
        print(f"  {label} trials={trials}: {results[trials]['time_mean']:.1f}s, "
              f"{results[trials]['gates_mean']:.0f} 2Q gates (min={results[trials]['gates_min']})")

    return results


def run_sweep_abstract_heavyhex():
    """Sweep trial counts on a chain circuit (cat-like) on heavy-hex."""
    # Import FlexibleBackend
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(RESULTS_DIR)))

    from benchpress.utilities.backends import FlexibleBackend
    from benchpress.utilities.io import qasm_circuit_loader

    # Use ising_n98 as representative chain circuit on heavy-hex
    qasm_dir = os.path.join(os.path.dirname(RESULTS_DIR), "QASMBench", "large")
    ising_path = None
    for root, dirs, files in os.walk(qasm_dir):
        for f in files:
            if "ising" in f and f.endswith(".qasm") and "n98" in f:
                ising_path = os.path.join(root, f)
                break

    if ising_path is None:
        # Try alternative path
        from benchpress.config import Configuration
        ising_path = Configuration.get_qasm_dir("QASMBench") + "large/ising_n98/ising_n98.qasm"

    from qiskit import QuantumCircuit
    try:
        circuit = QuantumCircuit.from_qasm_file(ising_path)
    except Exception:
        print("  Could not load ising_n98, skipping abstract heavy-hex sweep")
        return None

    backend = FlexibleBackend(circuit.num_qubits, "heavy-hex", control_flow=True)

    results = {}
    for trials in TRIAL_COUNTS:
        times = []
        gate_counts = []
        for rep in range(NUM_REPEATS):
            pm = generate_preset_pass_manager(optimization_level=2, backend=backend)
            _patch_sabre_trials(pm, layout_trials=trials, swap_trials=trials)

            t0 = time.perf_counter()
            trans_qc = pm.run(circuit)
            elapsed = time.perf_counter() - t0

            ops = trans_qc.count_ops()
            cz_count = ops.get("cz", 0) + ops.get("cx", 0) + ops.get("ecr", 0)

            times.append(elapsed)
            gate_counts.append(cz_count)

        results[trials] = {
            "time_mean": np.mean(times),
            "time_std": np.std(times),
            "gates_mean": np.mean(gate_counts),
            "gates_std": np.std(gate_counts),
            "gates_min": int(np.min(gate_counts)),
        }
        print(f"  ising_n98 heavy-hex trials={trials}: {results[trials]['time_mean']:.1f}s, "
              f"{results[trials]['gates_mean']:.0f} 2Q gates (min={results[trials]['gates_min']})")

    return results


def plot_results(qv_results, hh_results=None):
    """Plot trial count vs time and gate count."""
    ncols = 2 if hh_results else 1
    fig, axes = plt.subplots(2, ncols, figsize=(7 * ncols, 8))
    if ncols == 1:
        axes = axes.reshape(-1, 1)

    # QV_100
    trials = sorted(qv_results.keys())
    times = [qv_results[t]["time_mean"] for t in trials]
    time_err = [qv_results[t]["time_std"] for t in trials]
    gates = [qv_results[t]["gates_mean"] for t in trials]
    gate_err = [qv_results[t]["gates_std"] for t in trials]

    ax = axes[0, 0]
    ax.errorbar(trials, times, yerr=time_err, marker="o", capsize=4, color="#3498DB")
    ax.set_xlabel("Trial Count (layout = swap)")
    ax.set_ylabel("Compilation Time (s)")
    ax.set_title("QV_100 on FakeTorino — Time vs Trials")
    ax.grid(alpha=0.3)
    ax.axvline(x=20, color="gray", linestyle="--", alpha=0.5, label="Default (20)")
    ax.legend()

    ax = axes[1, 0]
    ax.errorbar(trials, gates, yerr=gate_err, marker="s", capsize=4, color="#E74C3C")
    ax.set_xlabel("Trial Count (layout = swap)")
    ax.set_ylabel("2Q Gate Count")
    ax.set_title("QV_100 on FakeTorino — Gate Quality vs Trials")
    ax.grid(alpha=0.3)
    ax.axvline(x=20, color="gray", linestyle="--", alpha=0.5, label="Default (20)")
    ax.legend()

    if hh_results:
        trials = sorted(hh_results.keys())
        times = [hh_results[t]["time_mean"] for t in trials]
        time_err = [hh_results[t]["time_std"] for t in trials]
        gates = [hh_results[t]["gates_mean"] for t in trials]
        gate_err = [hh_results[t]["gates_std"] for t in trials]

        ax = axes[0, 1]
        ax.errorbar(trials, times, yerr=time_err, marker="o", capsize=4, color="#3498DB")
        ax.set_xlabel("Trial Count (layout = swap)")
        ax.set_ylabel("Compilation Time (s)")
        ax.set_title("ising_n98 on Heavy-Hex — Time vs Trials")
        ax.grid(alpha=0.3)
        ax.axvline(x=20, color="gray", linestyle="--", alpha=0.5, label="Default (20)")
        ax.legend()

        ax = axes[1, 1]
        ax.errorbar(trials, gates, yerr=gate_err, marker="s", capsize=4, color="#E74C3C")
        ax.set_xlabel("Trial Count (layout = swap)")
        ax.set_ylabel("2Q Gate Count")
        ax.set_title("ising_n98 on Heavy-Hex — Gate Quality vs Trials")
        ax.grid(alpha=0.3)
        ax.axvline(x=20, color="gray", linestyle="--", alpha=0.5, label="Default (20)")
        ax.legend()

    fig.suptitle("SABRE Trial Count Sweep\n(layout_trials = swap_trials)", y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "prototype_sabre_trial_sweep.png"),
                dpi=150, bbox_inches="tight")
    print(f"\nSaved prototype_sabre_trial_sweep.png")


if __name__ == "__main__":
    print("=== SABRE Trial Count Sweep ===\n")

    print("Running QV_100 on FakeTorino...")
    qv_results = run_sweep_qv100()

    print("\nRunning ising_n98 on heavy-hex...")
    hh_results = run_sweep_abstract_heavyhex()

    # Save raw data
    data = {"qv100_faketorin": qv_results}
    if hh_results:
        data["ising_n98_heavyhex"] = hh_results
    with open(os.path.join(RESULTS_DIR, "prototype_sabre_trial_sweep.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved prototype_sabre_trial_sweep.json")

    plot_results(qv_results, hh_results)
    print("\nDone.")
