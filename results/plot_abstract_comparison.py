"""Generate comparison figures for abstract_transpile benchmarks."""

import json
import matplotlib.pyplot as plt
import numpy as np
import os

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
BENCH_DIR = os.path.join(os.path.dirname(RESULTS_DIR), ".benchmarks", "Linux-CPython-3.11-64bit")

with open(os.path.join(BENCH_DIR, "abstract_qiskit_medium.json")) as f:
    qi_med = json.load(f)
with open(os.path.join(BENCH_DIR, "abstract_qpanda_medium.json")) as f:
    qp_med = json.load(f)
with open(os.path.join(BENCH_DIR, "abstract_qiskit_large.json")) as f:
    qi_lrg = json.load(f)
with open(os.path.join(BENCH_DIR, "abstract_qpanda_large.json")) as f:
    qp_lrg = json.load(f)
with open(os.path.join(BENCH_DIR, "abstract_qiskit_adaptive_medium_v2.json")) as f:
    ad_med = json.load(f)
with open(os.path.join(BENCH_DIR, "abstract_qiskit_adaptive_large_v2.json")) as f:
    ad_lrg = json.load(f)


def parse(data, prefix):
    d = {}
    for b in data["benchmarks"]:
        raw = b["name"].replace(f"test_QASMBench_{prefix}[", "").rstrip("]")
        for topo in ["all-to-all", "square", "heavy-hex", "linear"]:
            if raw.endswith(topo):
                circuit = raw[: -(len(topo) + 1)]
                break
        else:
            continue
        ei = b.get("extra_info", {})
        d[(circuit, topo)] = {
            "time": b["stats"]["mean"],
            "cz": ei.get("output_gate_count_2q", 0),
            "depth_2q": ei.get("output_depth_2q", 0),
            "nq": ei.get("input_num_qubits", 0),
        }
    return d


qi_m = parse(qi_med, "medium")
qp_m = parse(qp_med, "medium")
qi_l = parse(qi_lrg, "large")
qp_l = parse(qp_lrg, "large")
ad_m = parse(ad_med, "medium")
ad_l = parse(ad_lrg, "large")

colors = {"qpanda": "#E74C3C", "qiskit": "#3498DB", "adaptive": "#2ECC71"}
topos = ["all-to-all", "square", "heavy-hex", "linear"]


# --- Figure 1: Compilation Time by Topology (Medium + Large combined) ---
fig1, (ax1a, ax1b) = plt.subplots(1, 2, figsize=(14, 5))

for ax, qi_d, qp_d, ad_d, title in [
    (ax1a, qi_m, qp_m, ad_m, "Medium (11-27Q)"),
    (ax1b, qi_l, qp_l, ad_l, "Large (28-433Q)"),
]:
    topo_times = {"qpanda": [], "qiskit": [], "adaptive": []}
    for topo in topos:
        common = [k for k in qi_d if k[1] == topo and k in qp_d]
        topo_times["qiskit"].append(sum(qi_d[k]["time"] for k in common))
        topo_times["qpanda"].append(sum(qp_d[k]["time"] for k in common))
        # Adaptive only applies to all-to-all
        if topo == "all-to-all":
            common_ad = [k for k in ad_d if k[1] == topo]
            topo_times["adaptive"].append(sum(ad_d[k]["time"] for k in common_ad))
        else:
            topo_times["adaptive"].append(None)

    x = np.arange(len(topos))
    width = 0.25
    ax.bar(x - width, topo_times["qpanda"], width, label="QPanda3", color=colors["qpanda"])
    ax.bar(x, topo_times["qiskit"], width, label="Qiskit Default", color=colors["qiskit"])
    # Only show adaptive bar on all-to-all (index 0)
    if topo_times["adaptive"][0] is not None:
        ax.bar([0 + width], [topo_times["adaptive"][0]], width,
               label="Qiskit Adaptive", color=colors["adaptive"])
    ax.set_yscale("log")
    ax.set_ylabel("Total Compilation Time (s, log scale)")
    ax.set_title(f"Abstract Transpile — {title}")
    ax.set_xticks(x)
    ax.set_xticklabels(topos, rotation=15)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # Annotate speedup on all-to-all
    qi_a2a = topo_times["qiskit"][0]
    ad_a2a = topo_times["adaptive"][0]
    if ad_a2a and ad_a2a > 0:
        ax.annotate(
            f"{qi_a2a / ad_a2a:.1f}x",
            xy=(0 + width, ad_a2a),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=colors["adaptive"],
            fontweight="bold",
        )

fig1.suptitle("Compilation Time by Topology\nIntel Xeon SPR, 160 vCPUs", y=1.02)
fig1.tight_layout()
fig1.savefig(os.path.join(RESULTS_DIR, "abstract_compilation_time.png"), dpi=150, bbox_inches="tight")
print("Saved abstract_compilation_time.png")


# --- Figure 2: Adaptive Speedup on All-to-All (per circuit, Large) ---
fig2, ax2 = plt.subplots(figsize=(12, 5))

common_a2a = sorted(
    [k for k in qi_l if k[1] == "all-to-all" and k in ad_l],
    key=lambda k: qi_l[k]["time"] / ad_l[k]["time"] if ad_l[k]["time"] > 0 else 0,
    reverse=True,
)

circuits = [k[0] for k in common_a2a]
speedups = [qi_l[k]["time"] / ad_l[k]["time"] for k in common_a2a]

# Truncate labels
short = {c: c[:15] + ".." if len(c) > 17 else c for c in circuits}
x = np.arange(len(circuits))

bars = ax2.bar(x, speedups, color=colors["adaptive"], edgecolor="white", linewidth=0.5)

# Color bars > 5x differently
for i, s in enumerate(speedups):
    if s > 5:
        bars[i].set_color("#27AE60")
    elif s < 1.5:
        bars[i].set_color("#95A5A6")

ax2.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
ax2.set_ylabel("Speedup (Adaptive / Default)")
ax2.set_title("Qiskit Adaptive Speedup on All-to-All — Large Circuits\n(skip layout/routing, level 2 optimization, identical gate output)")
ax2.set_xticks(x)
ax2.set_xticklabels([short[c] for c in circuits], rotation=70, ha="right", fontsize=7)
ax2.grid(axis="y", alpha=0.3)

# Annotate top speedups
for i, s in enumerate(speedups[:5]):
    ax2.annotate(f"{s:.0f}x", xy=(i, s), xytext=(0, 3), textcoords="offset points",
                 ha="center", fontsize=7, fontweight="bold")

fig2.tight_layout()
fig2.savefig(os.path.join(RESULTS_DIR, "abstract_adaptive_speedup.png"), dpi=150, bbox_inches="tight")
print("Saved abstract_adaptive_speedup.png")


# --- Figure 3: 2Q Gate Ratio by Topology (QPanda3/Qiskit, Medium + Large) ---
fig3, (ax3a, ax3b) = plt.subplots(1, 2, figsize=(14, 5))

for ax, qi_d, qp_d, title in [
    (ax3a, qi_m, qp_m, "Medium (11-27Q)"),
    (ax3b, qi_l, qp_l, "Large (28-433Q)"),
]:
    topo_ratios = []
    for topo in topos:
        ratios = []
        for k in qi_d:
            if k[1] == topo and k in qp_d and qi_d[k]["cz"] > 0 and qp_d[k]["cz"] > 0:
                ratios.append(qp_d[k]["cz"] / qi_d[k]["cz"])
        topo_ratios.append(ratios)

    bp = ax.boxplot(topo_ratios, tick_labels=topos, patch_artist=True, widths=0.5,
                    medianprops=dict(color="black", linewidth=2))
    for patch, topo in zip(bp["boxes"], topos):
        patch.set_facecolor("#AED6F1")
    ax.axhline(y=1.0, color="red", linestyle="--", alpha=0.7, label="Equal quality")
    ax.set_ylabel("QPanda3 / Qiskit 2Q Gate Ratio")
    ax.set_title(f"2Q Gate Quality — {title}\n(< 1.0 = QPanda3 better, > 1.0 = Qiskit better)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

fig3.suptitle("2Q Gate Count Ratio by Topology", y=1.02)
fig3.tight_layout()
fig3.savefig(os.path.join(RESULTS_DIR, "abstract_gate_quality.png"), dpi=150, bbox_inches="tight")
print("Saved abstract_gate_quality.png")


print("\nDone. Generated 3 figures in results/")
