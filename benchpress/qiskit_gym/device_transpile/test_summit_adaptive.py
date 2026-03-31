"""Adaptive transpilation: auto-classify circuits and apply tailored pass managers.

Circuit categories:
1. Dense Clifford   → CollectCliffords + LNN resynthesis before routing
2. Parameterized    → Reduce VF2Layout call_limit (100K, 500) to fail fast
3. Star topology    → StarPreRouting before SABRE
4. Default          → Standard level 2 pass manager
"""

from qiskit import QuantumCircuit
from qiskit.circuit.library import EfficientSU2, QuantumVolume
from qiskit.transpiler import PassManager
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit.transpiler.passes import VF2Layout
from qiskit.transpiler.passes.optimization.collect_cliffords import CollectCliffords
from qiskit.transpiler.passes.routing.star_prerouting import StarPreRouting
from qiskit.transpiler.passes.synthesis.high_level_synthesis import (
    HLSConfig,
    HighLevelSynthesis,
)

from benchpress.config import Configuration
from benchpress.utilities.io import (
    qasm_circuit_loader,
    input_circuit_properties,
    output_circuit_properties,
)
from benchpress.utilities.validation import circuit_validator
from benchpress.qiskit_gym.circuits import bv_all_ones

from benchpress.workouts.validation import benchpress_test_validation
from benchpress.workouts.device_transpile import WorkoutDeviceTranspile100Q
from benchpress.qiskit_gym.circuits import trivial_bvlike_circuit

BACKEND = Configuration.backend()
TWO_Q_GATE = BACKEND.two_q_gate_type
OPTIMIZATION_LEVEL = Configuration.options["qiskit"]["optimization_level"]

# --- Circuit classification ---

NON_CLIFFORD_GATES = frozenset({
    "rx", "ry", "rz", "rzz", "t", "tdg", "u1", "u2", "u3", "p", "cp",
    "rxx", "ryy", "r", "crx", "cry", "crz", "cu", "cu1", "cu3",
})


def _classify(circuit):
    """Classify a circuit into a transpilation strategy.

    Returns one of: 'clifford', 'parameterized', 'star', 'default'
    """
    ops = circuit.count_ops()
    op_names = set(ops.keys())
    num_qubits = circuit.num_qubits

    # 1. Parameterized circuits: have parameters or very few 2Q gates per qubit
    #    (EfficientSU2 arrives as a single high-level op before decomposition)
    if circuit.num_parameters > 0:
        return "parameterized"

    # Count 2Q gates
    total_2q = sum(
        count for name, count in ops.items()
        if name in ("cx", "cz", "swap", "ecr", "cp", "crx", "cry", "crz",
                     "rxx", "ryy", "rzz", "cswap", "iswap")
    )

    # 2. Dense Clifford: only Clifford gates + high 2Q density
    if not (op_names & NON_CLIFFORD_GATES):
        density = total_2q / max(num_qubits, 1)
        if density > 10:
            return "clifford"

    # 3. Star topology: one qubit appears in most 2Q gates
    if total_2q > 0 and num_qubits > 10:
        qubit_counts = {}
        for inst in circuit.data:
            if inst.operation.num_qubits >= 2:
                for q in inst.qubits:
                    idx = circuit.find_bit(q).index
                    qubit_counts[idx] = qubit_counts.get(idx, 0) + 1
        if qubit_counts:
            max_count = max(qubit_counts.values())
            # If one qubit is in >60% of 2Q gates, it's star-like
            if max_count > 0.6 * total_2q:
                return "star"

    return "default"


# --- Strategy implementations ---

def _make_default_pm():
    return generate_preset_pass_manager(OPTIMIZATION_LEVEL, BACKEND)


def _make_parameterized_pm():
    """Reduce VF2Layout call limit so it tries briefly then falls back to SABRE.

    Default level-2 VF2Layout uses call_limit=(5_000_000, 10_000) which can
    take ~98s to exhaust on circuits where VF2 cannot find a subgraph
    isomorphism (e.g. 89Q circular entanglement on 133Q heavy-hex).
    Reducing to (100_000, 500) lets VF2 succeed quickly when it can (~2s for
    100Q) while failing fast when it can't (~4s for 89Q).
    """
    pm = generate_preset_pass_manager(OPTIMIZATION_LEVEL, BACKEND)
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
    return pm


def _make_star_pm():
    """Inject StarPreRouting before the standard pass manager."""
    pm = generate_preset_pass_manager(OPTIMIZATION_LEVEL, BACKEND)
    pm.pre_init = PassManager([StarPreRouting()])
    return pm


def _preprocess_clifford(circuit):
    """Collect Clifford gates → resynthesize with LNN → decompose to primitives."""
    hls_config = HLSConfig(clifford=["lnn"])
    pre_pm = PassManager([
        CollectCliffords(),
        HighLevelSynthesis(hls_config=hls_config),
    ])
    processed = pre_pm.run(circuit)
    return processed.decompose(reps=1)


def _get_pm_and_circuit(circuit):
    """Return (pass_manager, possibly_preprocessed_circuit) based on classification."""
    strategy = _classify(circuit)
    if strategy == "clifford":
        return _make_default_pm(), _preprocess_clifford(circuit)
    elif strategy == "parameterized":
        return _make_parameterized_pm(), circuit
    elif strategy == "star":
        return _make_star_pm(), circuit
    else:
        return _make_default_pm(), circuit


# --- Tests ---

@benchpress_test_validation
class TestWorkoutDeviceTranspile100Q(WorkoutDeviceTranspile100Q):
    def test_QFT_100_transpile(self, benchmark):
        """Compile 100Q QFT circuit against target backend"""
        circuit = qasm_circuit_loader(
            Configuration.get_qasm_dir("qft") + "qft_N100.qasm", benchmark
        )
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_QV_100_transpile(self, benchmark):
        """Compile 100Q QV circuit against target backend"""
        circuit = QuantumVolume(100, 100, seed=12345)
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_circSU2_89_transpile(self, benchmark):
        """Compile 89Q circSU2 circuit against target backend"""
        circuit = EfficientSU2(89, reps=3, entanglement="circular")
        input_circuit_properties(circuit, benchmark)
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_circSU2_100_transpile(self, benchmark):
        """Compile 100Q circSU2 circuit against target backend"""
        circuit = EfficientSU2(100, reps=3, entanglement="circular")
        input_circuit_properties(circuit, benchmark)
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_BV_100_transpile(self, benchmark):
        """Compile 100Q BV circuit against target backend"""
        circuit = bv_all_ones(100)
        input_circuit_properties(circuit, benchmark)
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_square_heisenberg_100_transpile(self, benchmark):
        """Compile 100Q square-Heisenberg circuit against target backend"""
        circuit = qasm_circuit_loader(
            Configuration.get_qasm_dir("square-heisenberg")
            + "square_heisenberg_N100.qasm",
            benchmark,
        )
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_QAOA_100_transpile(self, benchmark):
        """Compile 100Q QAOA circuit against target backend"""
        circuit = qasm_circuit_loader(
            Configuration.get_qasm_dir("qaoa") + "qaoa_barabasi_albert_N100_3reps.qasm",
            benchmark,
        )
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_BVlike_simplification_transpile(self, benchmark):
        """Transpile a BV-like circuit that should collapse down
        into a single X and Z gate on a target device
        """
        circuit = trivial_bvlike_circuit(100)
        input_circuit_properties(circuit, benchmark)
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)

    def test_clifford_100_transpile(self, benchmark):
        """Compile 100Q Clifford circuit against target backend"""
        circuit = qasm_circuit_loader(
            Configuration.get_qasm_dir("clifford") + "clifford_100_12345.qasm",
            benchmark,
        )
        pm, circuit = _get_pm_and_circuit(circuit)

        @benchmark
        def result():
            return pm.run(circuit)

        output_circuit_properties(result, TWO_Q_GATE, benchmark)
        assert circuit_validator(result, BACKEND)
