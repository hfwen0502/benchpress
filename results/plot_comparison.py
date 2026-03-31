"""Generate comparison figures for device_transpile benchmarks."""

import json
import matplotlib.pyplot as plt
import numpy as np
import os

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
BENCH_DIR = os.path.join(os.path.dirname(RESULTS_DIR), ".benchmarks", "Linux-CPython-3.11-64bit")

with open(os.path.join(BENCH_DIR, "0005_server_qiskit_baseline_clean.json")) as f:
    qiskit = json.load(f)
with open(os.path.join(BENCH_DIR, "0006_server_qiskit_adaptive.json")) as f:
    adaptive = json.load(f)
with open(os.path.join(BENCH_DIR, "0004_server_qpanda_clean.json")) as f:
    qpanda = json.load(f)


def build(data):
    d = {}
    for b in data["benchmarks"]:
        name = b["name"].replace("test_", "").replace("_transpile", "")
        ei = b.get("extra_info", {})
        d[name] = {
            "time": b["stats"]["mean"],
            "cz": ei.get("output_gate_count_2q", 0),
            "depth_2q": ei.get("output_depth_2q", 0),
        }
    return d


qi = build(qiskit)
ad = build(adaptive)
qp = build(qpanda)

# Circuit display order (by Qiskit default time)
circuits = sorted(qi.keys(), key=lambda k: qi[k]["time"])
# Shorter labels
labels = {
    "BVlike_simplification": "BVlike",
    "BV_100": "BV",
    "circSU2_100": "SU2-100",
    "circSU2_89": "SU2-89",
    "square_heisenberg_100": "Heisen.",
    "QAOA_100": "QAOA",
    "QFT_100": "QFT",
    "clifford_100": "Clifford",
    "QV_100": "QV",
}

x_labels = [labels.get(c, c) for c in circuits]
x = np.arange(len(circuits))
width = 0.25

colors = {"qpanda": "#E74C3C", "qiskit": "#3498DB", "adaptive": "#2ECC71"}


# --- Figure 1: Compilation Time (log scale, absolute) ---
fig1, ax1 = plt.subplots(figsize=(10, 5))

times_qp = [qp[c]["time"] * 1000 for c in circuits]
times_qi = [qi[c]["time"] * 1000 for c in circuits]
times_ad = [ad[c]["time"] * 1000 for c in circuits]

bars1 = ax1.bar(x - width, times_qp, width, label="QPanda3", color=colors["qpanda"])
bars2 = ax1.bar(x, times_qi, width, label="Qiskit Default", color=colors["qiskit"])
bars3 = ax1.bar(x + width, times_ad, width, label="Qiskit Adaptive", color=colors["adaptive"])

ax1.set_yscale("log")
ax1.set_ylabel("Compilation Time (ms, log scale)")
ax1.set_title("Device Transpile Compilation Time — FakeTorino 133Q\nIntel Xeon SPR, 160 vCPUs")
ax1.set_xticks(x)
ax1.set_xticklabels(x_labels)
ax1.legend()
ax1.grid(axis="y", alpha=0.3)

# Add speedup annotations for interesting cases
for i, c in enumerate(circuits):
    if c == "circSU2_89":
        ratio = qi[c]["time"] / ad[c]["time"]
        ax1.annotate(f"{ratio:.0f}x", xy=(i + width, times_ad[i]),
                     xytext=(0, 5), textcoords="offset points",
                     ha="center", fontsize=7, color=colors["adaptive"], fontweight="bold")
    if c == "clifford_100":
        ratio = qi[c]["time"] / ad[c]["time"]
        ax1.annotate(f"{ratio:.1f}x", xy=(i + width, times_ad[i]),
                     xytext=(0, 5), textcoords="offset points",
                     ha="center", fontsize=7, color=colors["adaptive"], fontweight="bold")

fig1.tight_layout()
fig1.savefig(os.path.join(RESULTS_DIR, "compilation_time.png"), dpi=150)
print("Saved compilation_time.png")


# --- Figure 2: 2Q Gate Count (relative to Qiskit Default = 1.0) ---
fig2, ax2 = plt.subplots(figsize=(10, 5))

# Skip BVlike (0 gates)
circuits_gates = [c for c in circuits if qi[c]["cz"] > 0]
x_gates = np.arange(len(circuits_gates))
labels_gates = [labels.get(c, c) for c in circuits_gates]

rel_qp = [qp[c]["cz"] / qi[c]["cz"] for c in circuits_gates]
rel_qi = [1.0 for _ in circuits_gates]
rel_ad = [ad[c]["cz"] / qi[c]["cz"] for c in circuits_gates]

bars1 = ax2.bar(x_gates - width, rel_qp, width, label="QPanda3", color=colors["qpanda"])
bars2 = ax2.bar(x_gates, rel_qi, width, label="Qiskit Default", color=colors["qiskit"])
bars3 = ax2.bar(x_gates + width, rel_ad, width, label="Qiskit Adaptive", color=colors["adaptive"])

ax2.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
ax2.set_ylabel("2Q Gate Count (relative to Qiskit Default)")
ax2.set_title("2Q Gate Count Comparison — FakeTorino 133Q\n(lower is better, Qiskit Default = 1.0)")
ax2.set_xticks(x_gates)
ax2.set_xticklabels(labels_gates)
ax2.legend()
ax2.grid(axis="y", alpha=0.3)

# Add percentage labels on QPanda3 bars
for i, c in enumerate(circuits_gates):
    pct = (qp[c]["cz"] - qi[c]["cz"]) / qi[c]["cz"] * 100
    ax2.annotate(f"+{pct:.0f}%", xy=(i - width, rel_qp[i]),
                 xytext=(0, 3), textcoords="offset points",
                 ha="center", fontsize=7, color=colors["qpanda"])
    # Adaptive label if different from default
    pct_ad = (ad[c]["cz"] - qi[c]["cz"]) / qi[c]["cz"] * 100
    if abs(pct_ad) > 1:
        ax2.annotate(f"{pct_ad:+.0f}%", xy=(i + width, rel_ad[i]),
                     xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=7, color=colors["adaptive"])

fig2.tight_layout()
fig2.savefig(os.path.join(RESULTS_DIR, "gate_count.png"), dpi=150)
print("Saved gate_count.png")


# --- Figure 3: 2Q Depth (relative to Qiskit Default = 1.0) ---
fig3, ax3 = plt.subplots(figsize=(10, 5))

circuits_depth = [c for c in circuits if qi[c]["depth_2q"] > 0]
x_depth = np.arange(len(circuits_depth))
labels_depth = [labels.get(c, c) for c in circuits_depth]

rel_qp_d = [qp[c]["depth_2q"] / qi[c]["depth_2q"] for c in circuits_depth]
rel_qi_d = [1.0 for _ in circuits_depth]
rel_ad_d = [ad[c]["depth_2q"] / qi[c]["depth_2q"] for c in circuits_depth]

bars1 = ax3.bar(x_depth - width, rel_qp_d, width, label="QPanda3", color=colors["qpanda"])
bars2 = ax3.bar(x_depth, rel_qi_d, width, label="Qiskit Default", color=colors["qiskit"])
bars3 = ax3.bar(x_depth + width, rel_ad_d, width, label="Qiskit Adaptive", color=colors["adaptive"])

ax3.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
ax3.set_ylabel("2Q Depth (relative to Qiskit Default)")
ax3.set_title("2Q Circuit Depth Comparison — FakeTorino 133Q\n(lower is better, Qiskit Default = 1.0)")
ax3.set_xticks(x_depth)
ax3.set_xticklabels(labels_depth)
ax3.legend()
ax3.grid(axis="y", alpha=0.3)

# Add percentage labels
for i, c in enumerate(circuits_depth):
    pct = (qp[c]["depth_2q"] - qi[c]["depth_2q"]) / qi[c]["depth_2q"] * 100
    if abs(pct) > 3:
        ax3.annotate(f"+{pct:.0f}%" if pct > 0 else f"{pct:.0f}%",
                     xy=(i - width, rel_qp_d[i]),
                     xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=7, color=colors["qpanda"])
    pct_ad = (ad[c]["depth_2q"] - qi[c]["depth_2q"]) / qi[c]["depth_2q"] * 100
    if abs(pct_ad) > 3:
        ax3.annotate(f"{pct_ad:+.0f}%", xy=(i + width, rel_ad_d[i]),
                     xytext=(0, 3), textcoords="offset points",
                     ha="center", fontsize=7, color=colors["adaptive"])

fig3.tight_layout()
fig3.savefig(os.path.join(RESULTS_DIR, "gate_depth.png"), dpi=150)
print("Saved gate_depth.png")

print("\nDone. Generated 3 figures in results/")
