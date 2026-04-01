#!/usr/bin/env python3
"""Comparison chart: Autohypothesis vs Karpathy — same hardware, correct indexing."""

import json
import csv
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D

# ══════════════════════════════════════════════════════════
# 1. Load our 71 experiments
# ══════════════════════════════════════════════════════════
our_runs = []
karpathy_repro = []  # karpathy-k* reproduced on our HW
with open("experiments.jsonl") as f:
    for line in f:
        exp = json.loads(line)
        eid = exp["id"]
        if eid == "exp-001-upstream-benchmark":
            k_benchmark_bpb = exp["val_bpb"]  # 0.974441
            continue
        if eid.startswith("karpathy-"):
            karpathy_repro.append(exp)
            continue
        our_runs.append(exp)

our_runs.sort(key=lambda e: e.get("ordinal", 0) or 0)
karpathy_repro.sort(key=lambda e: e["id"])  # k00, k01, ..., k22

# ══════════════════════════════════════════════════════════
# 2. Load Karpathy's original TSV to get experiment indices
# ══════════════════════════════════════════════════════════
karpathy_orig = []
with open("research/karpathy_original_results.tsv") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        karpathy_orig.append({
            "description": row["description"],
            "val_bpb": float(row["val_bpb"]),
            "status": row["status"],
        })

# Map: find the original experiment index for each "keep" entry
kept_indices = [i for i, r in enumerate(karpathy_orig) if r["status"] == "keep"]
# kept_indices[0] → k00, kept_indices[1] → k01, etc.
assert len(kept_indices) == len(karpathy_repro), \
    f"Mismatch: {len(kept_indices)} kept in TSV vs {len(karpathy_repro)} karpathy-k* runs"

# Build Karpathy reproduced data with correct x positions
k_repro_points = []
for k_idx, orig_idx in enumerate(kept_indices):
    k_repro_points.append({
        "x": orig_idx,                          # original experiment #
        "bpb": karpathy_repro[k_idx]["val_bpb"], # reproduced on our HW
        "desc": karpathy_orig[orig_idx]["description"],
    })

KARPATHY_TOTAL_RUNS = len(karpathy_orig)  # 126

# ══════════════════════════════════════════════════════════
# 3. Compute running-best trajectories
# ══════════════════════════════════════════════════════════

# Our running best (over all 71 experiments)
our_best_so_far = []
best = float("inf")
for r in our_runs:
    bpb = r["val_bpb"]
    if r["status"] == "keep" and 0 < bpb < best:
        best = bpb
    our_best_so_far.append(best if best < float("inf") else None)

# Karpathy reproduced running best (over 23 kept steps, at original indices)
k_best_so_far = []
best = float("inf")
for pt in k_repro_points:
    if pt["bpb"] < best:
        best = pt["bpb"]
    k_best_so_far.append(best)

# Key metrics
our_best = min(r["val_bpb"] for r in our_runs if r["status"] == "keep" and r["val_bpb"] > 0)
k_repro_best = min(pt["bpb"] for pt in k_repro_points)

# First beat: when our running best drops below Karpathy's benchmark (0.974441)
first_beat_idx = None
for i, bsf in enumerate(our_best_so_far):
    if bsf is not None and bsf < k_benchmark_bpb:
        first_beat_idx = i
        break

# Use ordinal (matches dashboard "Run #13")
beat_exp = our_runs[first_beat_idx] if first_beat_idx is not None else None
beat_num = beat_exp.get("ordinal", first_beat_idx + 1) if beat_exp else "?"

# ══════════════════════════════════════════════════════════
# 4. Plot
# ══════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(18, 8.5))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")
ax.grid(True, alpha=0.15, linewidth=0.5, color="#888")
ax.set_axisbelow(True)

# ── Karpathy reproduced kept dots + connecting line (blue) ──
k_xs = [pt["x"] for pt in k_repro_points]
k_ys = [pt["bpb"] for pt in k_repro_points]
ax.plot(k_xs, k_ys, color="#3B82F6", linewidth=1.2, alpha=0.45, zorder=3)
ax.scatter(k_xs, k_ys, c="#3B82F6", s=55, alpha=0.7, zorder=4,
           edgecolors="white", linewidths=0.6)

# ── Karpathy running-best step line (blue) ──
# Build step coordinates: at each kept index, the best-so-far changes;
# extend horizontally to the next kept index
k_step_x = []
k_step_y = []
for i, (pt, bsf) in enumerate(zip(k_repro_points, k_best_so_far)):
    k_step_x.append(pt["x"])
    k_step_y.append(bsf)
    # Extend to next point (or end of search)
    if i < len(k_repro_points) - 1:
        k_step_x.append(k_repro_points[i + 1]["x"])
        k_step_y.append(bsf)
# Extend to end of Karpathy's search
k_step_x.append(KARPATHY_TOTAL_RUNS - 1)
k_step_y.append(k_best_so_far[-1])
ax.plot(k_step_x, k_step_y, color="#3B82F6", linewidth=2.5, alpha=0.85, zorder=3)

# ── Karpathy labels on kept milestones (skip — too cluttered) ──

# ── Our discarded (gray dots) ──
our_disc = [(i, our_runs[i]["val_bpb"]) for i in range(len(our_runs))
            if our_runs[i]["status"] == "discard" and 0 < our_runs[i]["val_bpb"] < 1.1]
if our_disc:
    dx, dy = zip(*our_disc)
    ax.scatter(dx, dy, c="#C0C0C0", s=22, alpha=0.4, zorder=5)

# ── Our kept (green dots) ──
our_kept = [(i, our_runs[i]["val_bpb"]) for i in range(len(our_runs))
            if our_runs[i]["status"] == "keep" and our_runs[i]["val_bpb"] > 0]
if our_kept:
    ox, oy = zip(*our_kept)
    ax.scatter(ox, oy, c="#16A34A", s=60, alpha=0.85, zorder=7,
               edgecolors="white", linewidths=0.8)

# ── Our running-best step line (green) ──
our_valid = [(i, v) for i, v in enumerate(our_best_so_far) if v is not None and v < float("inf")]
if our_valid:
    sx, sy = zip(*our_valid)
    ax.step(sx, sy, where="post", color="#16A34A", linewidth=2.5, alpha=0.8, zorder=6)

# ── Our labels on kept milestones (skip — too cluttered) ──

# ── Karpathy benchmark dashed line ──
ax.axhline(y=k_benchmark_bpb, color="#3B82F6", linestyle="--", linewidth=1.5, alpha=0.35, zorder=1)
ax.text(KARPATHY_TOTAL_RUNS - 2, k_benchmark_bpb + 0.0004,
        f"Karpathy final config on our HW: {k_benchmark_bpb:.4f}",
        ha="right", va="bottom", fontsize=8.5, color="#3B82F6", fontweight="600", alpha=0.6)

# ── Beat annotation ──
if first_beat_idx is not None:
    beat_bpb = our_best_so_far[first_beat_idx]
    ax.scatter([first_beat_idx], [beat_bpb], s=220, facecolors="none",
               edgecolors="#16A34A", linewidths=2.5, zorder=9, alpha=0.9)
    ax.annotate(
        f"  beat Karpathy @ #{beat_num}  ",
        xy=(first_beat_idx, beat_bpb),
        xytext=(first_beat_idx + 15, beat_bpb + 0.012),
        fontsize=12, fontweight="bold", color="#16A34A",
        arrowprops=dict(arrowstyle="-|>", color="#16A34A", lw=2, mutation_scale=14),
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#E8F5E9", edgecolor="#16A34A",
                  alpha=0.95, linewidth=1.5),
        zorder=10,
    )

# ── "Our search ends" / "Karpathy still searching" markers ──
ax.axvline(x=len(our_runs) - 1, color="#16A34A", linestyle=":", linewidth=1, alpha=0.3)
ax.text(len(our_runs) + 0.5, ax.get_ylim()[0] if ax.get_ylim()[0] else 0.97,
        f"our search ends\n({len(our_runs)} runs)", fontsize=8, color="#16A34A",
        alpha=0.5, ha="left", va="bottom")

# ══════════════════════════════════════════════════════════
# 5. Axes, title, legend
# ══════════════════════════════════════════════════════════

# Y range
all_bpb = [r["val_bpb"] for r in our_runs if 0 < r["val_bpb"] < 1.1]
all_bpb += [pt["bpb"] for pt in k_repro_points]
y_lo = min(all_bpb) - 0.002
y_hi = max(all_bpb) + 0.002
ax.set_ylim(y_lo, y_hi)
ax.set_xlim(-2, KARPATHY_TOTAL_RUNS + 5)

ax.set_xlabel("Experiment #", fontsize=13, fontweight="500", labelpad=8)
ax.set_ylabel("Validation BPB (lower is better)", fontsize=13, fontweight="500", labelpad=8)
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.3f"))
ax.set_xticks(list(range(0, KARPATHY_TOTAL_RUNS + 10, 10)))

our_kept_n = len([r for r in our_runs if r["status"] == "keep"])
ax.set_title(
    f"Autohypothesis beat Karpathy's {KARPATHY_TOTAL_RUNS}-run result in {beat_num} experiments\n"
    f"(all results on same hardware — NVIDIA H100 80GB)",
    fontsize=16, fontweight="700", pad=14,
)

legend_elements = [
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#C0C0C0", markersize=5,
           linewidth=0, alpha=0.5, label="Discarded"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#16A34A", markersize=8,
           linewidth=0, alpha=0.85, label="Kept (Autohypothesis)"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#3B82F6", markersize=7,
           linewidth=0, alpha=0.7, label="Kept (Karpathy)"),
    Line2D([0], [0], color="#16A34A", linewidth=2.5, alpha=0.8,
           label="Running best — Autohypothesis"),
    Line2D([0], [0], color="#3B82F6", linewidth=2.5, alpha=0.85,
           label="Running best — Karpathy (same HW)"),
]
ax.legend(handles=legend_elements, loc="upper right", fontsize=10, framealpha=0.95,
          edgecolor="#ddd", fancybox=True)

# ── X / Twitter handles ──
fig.text(0.97, 0.02, "@kylecompute  @yimothysu  @patrikkml",
         ha="right", va="bottom", fontsize=11, color="#999",
         fontstyle="italic", transform=fig.transFigure)

plt.tight_layout()
plt.savefig("comparison_chart.png", dpi=200, bbox_inches="tight", facecolor="white")
plt.savefig("comparison_chart.svg", bbox_inches="tight", facecolor="white")
print("Saved comparison_chart.png and comparison_chart.svg")
print(f"\nOur best:            {our_best:.6f}  ({len(our_runs)} runs)")
print(f"Karpathy repro best: {k_repro_best:.6f}  ({KARPATHY_TOTAL_RUNS} runs)")
print(f"Karpathy benchmark:  {k_benchmark_bpb:.6f}  (final config, our HW)")
print(f"First beat:          experiment #{first_beat_idx + 1 if first_beat_idx else '?'}")
