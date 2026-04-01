"""Adaptive abstract transpilation: topology-aware pass manager selection.

Strategies:
1. all-to-all  → Skip layout/routing (unnecessary for fully-connected)
2. chain on heavy-hex → Pre-layout along a long path, then SABRE routing
3. default     → Standard level 2 pass manager
"""

import pytest
import rustworkx as rx

from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import SetLayout, FullAncillaAllocation, EnlargeWithAncilla, ApplyLayout
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from benchpress.workouts.validation import benchpress_test_validation
from benchpress.config import Configuration
from benchpress.utilities.backends import FlexibleBackend
from benchpress.utilities.io import qasm_circuit_loader, output_circuit_properties
from benchpress.utilities.validation import circuit_validator

from benchpress.workouts.abstract_transpile import (
    WorkoutAbstractQasmBenchSmall,
    WorkoutAbstractQasmBenchMedium,
    WorkoutAbstractQasmBenchLarge,
)
from benchpress.workouts.abstract_transpile.qasmbench import (
    SMALL_CIRC_TOPO,
    SMALL_NAMES,
    MEDIUM_CIRC_TOPO,
    MEDIUM_NAMES,
    LARGE_CIRC_TOPO,
    LARGE_NAMES,
)

OPTIMIZATION_LEVEL = Configuration.options["qiskit"]["optimization_level"]


def _is_chain_circuit(circuit, threshold=0.75):
    """Check if most 2Q gates operate on consecutive virtual qubits."""
    total_2q = 0
    consecutive_2q = 0
    for inst in circuit.data:
        if inst.operation.num_qubits == 2:
            total_2q += 1
            q0 = circuit.find_bit(inst.qubits[0]).index
            q1 = circuit.find_bit(inst.qubits[1]).index
            if abs(q0 - q1) == 1:
                consecutive_2q += 1
    return total_2q > 0 and (consecutive_2q / total_2q) > threshold


def _find_long_path(coupling_map, min_length):
    """Find a simple path of at least min_length on the coupling map.

    Heavy-hex has rows of degree-2/3 nodes connected by vertical bridges.
    Starting from a degree-1 endpoint and always picking the lowest-index
    unvisited neighbor traces the backbone (~83% of nodes). Any remaining
    qubits are assigned to leftover physical nodes.
    """
    graph = coupling_map.graph
    # CouplingMap uses a directed graph; get undirected neighbor sets
    if hasattr(graph, 'to_undirected'):
        ugraph = graph.to_undirected()
    else:
        ugraph = graph  # already undirected (e.g. from heavy_hex_graph)

    # Start from degree-1 nodes (endpoints) for best backbone coverage
    nodes_by_degree = sorted(
        ugraph.node_indices(), key=lambda n: ugraph.degree(n)
    )
    best_path = []

    for start in nodes_by_degree[:10]:
        path = [start]
        visited = {start}
        current = start
        while True:
            neighbors = sorted(
                n for n in ugraph.neighbors(current) if n not in visited
            )
            if not neighbors:
                break
            current = neighbors[0]
            path.append(current)
            visited.add(current)
        if len(path) > len(best_path):
            best_path = path
        if len(path) >= min_length:
            return path

    # If backbone path is shorter than needed, append remaining physical
    # qubits (not on the path) so SABRE can place the extra virtual qubits
    if len(best_path) < min_length:
        on_path = set(best_path)
        remaining = [n for n in ugraph.node_indices() if n not in on_path]
        best_path.extend(remaining[: min_length - len(best_path)])

    return best_path


def _get_pm(topology, backend, circuit=None):
    """Return a pass manager tailored to the topology and circuit structure.

    For all-to-all: skip layout/routing (unnecessary for fully-connected).
    For heavy-hex + chain circuit: pre-layout along a long backbone path.
    For everything else: standard level 2 with full routing.
    """
    if topology == "all-to-all":
        pm = generate_preset_pass_manager(
            optimization_level=OPTIMIZATION_LEVEL, backend=backend
        )
        pm.layout = None
        pm.routing = None
        return pm

    if (
        topology == "heavy-hex"
        and circuit is not None
        and _is_chain_circuit(circuit)
    ):
        path = _find_long_path(backend.coupling_map, circuit.num_qubits)
        if len(path) >= circuit.num_qubits:
            layout = path[: circuit.num_qubits]
            pm = generate_preset_pass_manager(
                optimization_level=OPTIMIZATION_LEVEL, backend=backend
            )
            pm.layout = PassManager([
                SetLayout(layout),
                FullAncillaAllocation(backend.coupling_map),
                EnlargeWithAncilla(),
                ApplyLayout(),
            ])
            return pm

    return generate_preset_pass_manager(
        optimization_level=OPTIMIZATION_LEVEL, backend=backend
    )


@benchpress_test_validation
class TestWorkoutAbstractQasmBenchSmall(WorkoutAbstractQasmBenchSmall):
    @pytest.mark.parametrize("circ_and_topo", SMALL_CIRC_TOPO, ids=SMALL_NAMES)
    def test_QASMBench_small(self, benchmark, circ_and_topo):
        circuit = qasm_circuit_loader(circ_and_topo[0], benchmark)
        backend = FlexibleBackend(
            circuit.num_qubits, circ_and_topo[1], control_flow=True
        )
        pm = _get_pm(circ_and_topo[1], backend, circuit)

        @benchmark
        def result():
            trans_qc = pm.run(circuit)
            return trans_qc

        output_circuit_properties(result, backend.two_q_gate_type, benchmark)
        assert circuit_validator(result, backend)


@benchpress_test_validation
class TestWorkoutAbstractQasmBenchMedium(WorkoutAbstractQasmBenchMedium):
    @pytest.mark.parametrize("circ_and_topo", MEDIUM_CIRC_TOPO, ids=MEDIUM_NAMES)
    def test_QASMBench_medium(self, benchmark, circ_and_topo):
        circuit = qasm_circuit_loader(circ_and_topo[0], benchmark)
        backend = FlexibleBackend(
            circuit.num_qubits, circ_and_topo[1], control_flow=True
        )
        pm = _get_pm(circ_and_topo[1], backend, circuit)

        @benchmark
        def result():
            trans_qc = pm.run(circuit)
            return trans_qc

        output_circuit_properties(result, backend.two_q_gate_type, benchmark)
        assert circuit_validator(result, backend)


@benchpress_test_validation
class TestWorkoutAbstractQasmBenchLarge(WorkoutAbstractQasmBenchLarge):
    @pytest.mark.parametrize("circ_and_topo", LARGE_CIRC_TOPO, ids=LARGE_NAMES)
    def test_QASMBench_large(self, benchmark, circ_and_topo):
        circuit = qasm_circuit_loader(circ_and_topo[0], benchmark)
        backend = FlexibleBackend(
            circuit.num_qubits, circ_and_topo[1], control_flow=True
        )
        pm = _get_pm(circ_and_topo[1], backend, circuit)

        @benchmark
        def result():
            trans_qc = pm.run(circuit)
            return trans_qc

        output_circuit_properties(result, backend.two_q_gate_type, benchmark)
        assert circuit_validator(result, backend)
