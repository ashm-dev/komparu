#!/usr/bin/env python3
"""Generate hand-drawn style benchmark charts for README.

Uses matplotlib xkcd style for a distinctive sketchy look.
Outputs SVG files to benchmarks/charts/.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patheffects as pe
import numpy as np

RESULTS = Path(__file__).parent / "results" / "all_results.json"
CHARTS = Path(__file__).parent / "charts"

# Colors — distinctive, high contrast, colorblind-friendly
COLORS = {
    "komparu":       "#e8453c",  # red
    "filecmp":       "#4a90d9",  # blue
    "hashlib_sha256":"#8b8b8b",  # gray
    "cmp":           "#f5a623",  # orange
    "go":            "#50c878",  # green
    "rust":          "#c084fc",  # purple
    "diff":          "#a0a0a0",  # light gray
}

LABELS = {
    "komparu":       "komparu",
    "filecmp":       "filecmp (stdlib)",
    "hashlib_sha256":"hashlib SHA-256",
    "cmp":           "cmp -s (POSIX)",
    "go":            "Go 1.25",
    "rust":          "Rust 1.93",
    "diff":          "diff -q (GNU)",
}

MARKERS = {
    "komparu":       "o",
    "filecmp":       "s",
    "hashlib_sha256":"^",
    "cmp":           "D",
    "go":            "v",
    "rust":          "P",
    "diff":          "X",
}

SIZE_ORDER = ["1MB", "10MB", "100MB", "1GB"]
SIZE_BYTES = {"1MB": 1e6, "10MB": 10e6, "100MB": 100e6, "1GB": 1e9}


def load_data():
    with open(RESULTS) as f:
        return json.load(f)


def fmt_time_axis(val, _):
    """Format seconds for Y axis."""
    if val >= 1:
        return f"{val:.1f}s"
    elif val >= 0.001:
        return f"{val*1000:.0f}ms"
    elif val >= 0.000001:
        return f"{val*1e6:.0f}us"
    return f"{val:.1e}"


def plot_file_identical(data: dict):
    """Line chart: file size vs time for identical files."""
    file_data = data["file"]

    fig, ax = plt.subplots(figsize=(10, 6))

    tools = ["komparu", "filecmp", "cmp", "go", "rust", "hashlib_sha256"]
    x_vals = np.arange(len(SIZE_ORDER))

    for tool in tools:
        times = []
        for size in SIZE_ORDER:
            key = f"file_{size}_identical"
            if key in file_data and tool in file_data[key]:
                times.append(file_data[key][tool]["median"])
            else:
                times.append(None)

        valid = [(x, t) for x, t in zip(x_vals, times) if t is not None]
        if valid:
            xs, ts = zip(*valid)
            ax.plot(xs, ts, color=COLORS[tool], marker=MARKERS[tool],
                    markersize=8, linewidth=2.5, label=LABELS[tool],
                    zorder=10 if tool == "komparu" else 5)

    ax.set_yscale("log")
    ax.set_xticks(x_vals)
    ax.set_xticklabels(SIZE_ORDER, fontsize=12)
    ax.set_xlabel("File Size", fontsize=13, fontweight="bold")
    ax.set_ylabel("Time (log scale)", fontsize=13, fontweight="bold")
    ax.set_title("Identical Files - Full Comparison", fontsize=15, fontweight="bold")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(fmt_time_axis))
    ax.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(CHARTS / "file_identical.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/file_identical.png")


def plot_file_differ_last(data: dict):
    """Line chart: file size vs time for differ-last-byte scenario."""
    file_data = data["file"]

    fig, ax = plt.subplots(figsize=(10, 6))

    tools = ["komparu", "filecmp", "cmp", "go", "rust", "hashlib_sha256"]
    x_vals = np.arange(len(SIZE_ORDER))

    for tool in tools:
        times = []
        for size in SIZE_ORDER:
            key = f"file_{size}_differ_last"
            if key in file_data and tool in file_data[key]:
                times.append(file_data[key][tool]["median"])
            else:
                times.append(None)

        valid = [(x, t) for x, t in zip(x_vals, times) if t is not None]
        if valid:
            xs, ts = zip(*valid)
            ax.plot(xs, ts, color=COLORS[tool], marker=MARKERS[tool],
                    markersize=8, linewidth=2.5, label=LABELS[tool],
                    zorder=10 if tool == "komparu" else 5)

    ax.set_yscale("log")
    ax.set_xticks(x_vals)
    ax.set_xticklabels(SIZE_ORDER, fontsize=12)
    ax.set_xlabel("File Size", fontsize=13, fontweight="bold")
    ax.set_ylabel("Time (log scale)", fontsize=13, fontweight="bold")
    ax.set_title("Last Byte Differs - Quick Check Advantage",
                 fontsize=15, fontweight="bold")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(fmt_time_axis))
    ax.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax.grid(True, alpha=0.3)

    # Annotation for komparu flat line
    ax.annotate("quick_check: O(1)",
                xy=(3, data["file"]["file_1GB_differ_last"]["komparu"]["median"]),
                xytext=(1.5, 0.0005),
                fontsize=11, fontweight="bold", color=COLORS["komparu"],
                arrowprops=dict(arrowstyle="->", color=COLORS["komparu"], lw=1.5))

    fig.tight_layout()
    fig.savefig(CHARTS / "file_differ_last.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/file_differ_last.png")


def plot_file_differ_quarter(data: dict):
    """Line chart: file size vs time for differ-at-25% scenario (no quick_check hit)."""
    file_data = data["file"]

    fig, ax = plt.subplots(figsize=(10, 6))

    tools = ["komparu", "filecmp", "cmp", "go", "rust", "hashlib_sha256"]
    x_vals = np.arange(len(SIZE_ORDER))

    for tool in tools:
        times = []
        for size in SIZE_ORDER:
            key = f"file_{size}_differ_quarter"
            if key in file_data and tool in file_data[key]:
                times.append(file_data[key][tool]["median"])
            else:
                times.append(None)

        valid = [(x, t) for x, t in zip(x_vals, times) if t is not None]
        if valid:
            xs, ts = zip(*valid)
            ax.plot(xs, ts, color=COLORS[tool], marker=MARKERS[tool],
                    markersize=8, linewidth=2.5, label=LABELS[tool],
                    zorder=10 if tool == "komparu" else 5)

    ax.set_yscale("log")
    ax.set_xticks(x_vals)
    ax.set_xticklabels(SIZE_ORDER, fontsize=12)
    ax.set_xlabel("File Size", fontsize=13, fontweight="bold")
    ax.set_ylabel("Time (log scale)", fontsize=13, fontweight="bold")
    ax.set_title("Differ at 25% - Sequential Scan (no quick_check hit)",
                 fontsize=15, fontweight="bold")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(fmt_time_axis))
    ax.legend(loc="upper left", fontsize=10, framealpha=0.9)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(CHARTS / "file_differ_quarter.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/file_differ_quarter.png")


def plot_dir_comparison(data: dict):
    """Grouped bar chart for directory benchmarks."""
    dir_data = data["dir"]

    scenarios = ["dir_100x1MB_identical", "dir_100x1MB_1differ", "dir_1000x100KB_identical"]
    labels = ["100x1MB\nidentical", "100x1MB\n1 differs", "1000x100KB\nidentical"]
    tools = ["komparu", "filecmp", "go", "rust"]

    fig, ax = plt.subplots(figsize=(10, 5))

    n_tools = len(tools)
    bar_width = 0.18
    x = np.arange(len(scenarios))

    for i, tool in enumerate(tools):
        times = []
        for sc in scenarios:
            if sc in dir_data and tool in dir_data[sc]:
                times.append(dir_data[sc][tool]["median"] * 1000)  # ms
            else:
                times.append(0)

        offset = (i - n_tools / 2 + 0.5) * bar_width
        bars = ax.bar(x + offset, times, bar_width, label=LABELS[tool],
                      color=COLORS[tool], edgecolor="black", linewidth=0.5,
                      zorder=5)

        # Value labels on bars
        for bar, t in zip(bars, times):
            if t > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{t:.0f}ms", ha="center", va="bottom", fontsize=8,
                        fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("Time (ms)", fontsize=13, fontweight="bold")
    ax.set_title("Directory Comparison", fontsize=15, fontweight="bold")
    ax.legend(fontsize=10, framealpha=0.9)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(CHARTS / "dir_comparison.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/dir_comparison.png")


def plot_speedup_heatmap(data: dict):
    """Heatmap showing komparu speedup vs competitors."""
    file_data = data["file"]

    scenarios = []
    for size in SIZE_ORDER:
        for sc in ["identical", "differ_quarter", "differ_last"]:
            scenarios.append(f"{size} {sc}")

    rivals = ["filecmp", "cmp", "go", "rust", "hashlib_sha256"]
    rival_labels = ["filecmp", "cmp -s", "Go", "Rust", "SHA-256"]

    matrix = []
    for size in SIZE_ORDER:
        for sc in ["identical", "differ_quarter", "differ_last"]:
            key = f"file_{size}_{sc}"
            row = []
            komparu_t = file_data[key]["komparu"]["median"]
            for rival in rivals:
                if rival in file_data[key] and komparu_t > 0:
                    speedup = file_data[key][rival]["median"] / komparu_t
                    row.append(speedup)
                else:
                    row.append(1.0)
            matrix.append(row)

    matrix = np.array(matrix)
    log_matrix = np.log10(np.clip(matrix, 0.1, None))

    fig, ax = plt.subplots(figsize=(10, 8))

    im = ax.imshow(log_matrix, cmap="RdYlGn", aspect="auto",
                   vmin=-0.5, vmax=4.5)

    ax.set_xticks(range(len(rival_labels)))
    ax.set_xticklabels(rival_labels, fontsize=11, fontweight="bold")
    ax.set_yticks(range(len(scenarios)))
    ax.set_yticklabels(scenarios, fontsize=10)
    ax.set_title("komparu Speedup vs Competitors", fontsize=15, fontweight="bold")

    # Text annotations
    for i in range(len(scenarios)):
        for j in range(len(rivals)):
            val = matrix[i][j]
            if val >= 10:
                text = f"{val:.0f}x"
            elif val >= 1:
                text = f"{val:.1f}x"
            else:
                text = f"{val:.2f}x"
            color = "white" if log_matrix[i][j] > 2.5 or log_matrix[i][j] < -0.2 else "black"
            stroke = "black" if color == "white" else "white"
            ax.text(j, i, text, ha="center", va="center",
                    fontsize=9, fontweight="bold", color=color,
                    path_effects=[
                        pe.withStroke(linewidth=3, foreground=stroke),
                    ])

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Speedup (log10)", fontsize=11)
    cbar.set_ticks([0, 1, 2, 3, 4])
    cbar.set_ticklabels(["1x", "10x", "100x", "1000x", "10000x"])

    fig.tight_layout()
    fig.savefig(CHARTS / "speedup_heatmap.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/speedup_heatmap.png")


MEMORY_RESULTS = Path(__file__).parent / "results" / "memory_results.json"


def plot_memory_usage(mem_data: dict):
    """Bar chart: Python heap allocation for each tool across file sizes."""
    tools = ["komparu", "filecmp (deep)", "hashlib SHA-256"]
    tool_labels = ["komparu", "filecmp", "hashlib"]
    tool_colors = [COLORS["komparu"], COLORS["filecmp"], COLORS["hashlib_sha256"]]

    sizes = []
    for key in sorted(mem_data.keys()):
        size = key.split("_")[1]
        sizes.append(size)

    fig, ax = plt.subplots(figsize=(10, 5))

    n_tools = len(tools)
    bar_width = 0.22
    x = np.arange(len(sizes))

    for i, (tool, label, color) in enumerate(zip(tools, tool_labels, tool_colors)):
        vals = []
        for size in sizes:
            key = f"memory_{size}_identical"
            if key in mem_data and tool in mem_data[key]:
                heap = mem_data[key][tool].get("peak_heap_bytes", 0)
                vals.append(heap / 1024)  # KB
            else:
                vals.append(0)

        offset = (i - n_tools / 2 + 0.5) * bar_width
        bars = ax.bar(x + offset, vals, bar_width, label=label,
                      color=color, edgecolor="black", linewidth=0.5, zorder=5)

        for bar, v in zip(bars, vals):
            if v > 0:
                if v >= 1024:
                    label_text = f"{v/1024:.0f}MB"
                elif v >= 1:
                    label_text = f"{v:.0f}KB"
                else:
                    label_text = f"{v*1024:.0f}B"
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        label_text, ha="center", va="bottom", fontsize=8,
                        fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(sizes, fontsize=11)
    ax.set_yscale("log")
    ax.set_ylabel("Peak Heap (KB, log scale)", fontsize=13, fontweight="bold")
    ax.set_title("Python Heap Allocation During Comparison", fontsize=15, fontweight="bold")
    ax.legend(fontsize=10, framealpha=0.9)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(CHARTS / "memory_usage.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/memory_usage.png")


def plot_radar(data: dict, mem_data: dict | None = None):
    """Radar chart: multi-dimensional comparison (speed, memory, scalability)."""
    file_data = data["file"]
    dir_data = data["dir"]

    # Dimensions: speed (identical 1GB), speed (differ_quarter 1GB),
    #             dir speed, memory efficiency
    # For each tool, compute scores (higher = better, normalized to komparu=1.0)

    tools = ["komparu", "filecmp", "go", "rust"]
    tool_labels = ["komparu", "filecmp", "Go", "Rust"]
    tool_colors = [COLORS["komparu"], COLORS["filecmp"], COLORS["go"], COLORS["rust"]]

    komparu_id = file_data.get("file_1GB_identical", {}).get("komparu", {}).get("median", 1)
    komparu_dq = file_data.get("file_1GB_differ_quarter", {}).get("komparu", {}).get("median", 1)
    komparu_dir = dir_data.get("dir_100x1MB_identical", {}).get("komparu", {}).get("median", 1)

    dimensions = ["Identical 1GB\n(speed)", "Differ at 25% 1GB\n(speed)",
                  "Dir 100x1MB\n(speed)", "Small files 1MB\n(speed)"]

    komparu_small = file_data.get("file_1MB_identical", {}).get("komparu", {}).get("median", 1)

    scores = {}
    for tool, label in zip(tools, tool_labels):
        s_id = file_data.get("file_1GB_identical", {}).get(tool, {}).get("median", 999)
        s_dq = file_data.get("file_1GB_differ_quarter", {}).get(tool, {}).get("median", 999)
        s_dir = dir_data.get("dir_100x1MB_identical", {}).get(tool, {}).get("median", 999)
        s_small = file_data.get("file_1MB_identical", {}).get(tool, {}).get("median", 999)

        # Score = how much faster than the tool (komparu_time / tool_time)
        # Higher = better for the tool
        scores[label] = [
            komparu_id / s_id if s_id > 0 else 0,   # normalized: 1.0 for same speed
            komparu_dq / s_dq if s_dq > 0 else 0,
            komparu_dir / s_dir if s_dir > 0 else 0,
            komparu_small / s_small if s_small > 0 else 0,
        ]

    # Invert: we want "faster = bigger on radar"
    # Current: komparu/tool_time, so for komparu it's 1.0, for slower tools < 1.0
    # We want: tool_time / komparu_time, so faster tools score higher
    for label in scores:
        scores[label] = [1.0 / s if s > 0 else 0 for s in scores[label]]

    N = len(dimensions)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # close the polygon

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    for label, color in zip(tool_labels, tool_colors):
        vals = scores[label] + scores[label][:1]
        ax.plot(angles, vals, "o-", color=color, linewidth=2, markersize=6, label=label)
        ax.fill(angles, vals, alpha=0.1, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dimensions, fontsize=10, fontweight="bold")
    ax.set_title("Multi-Dimensional Comparison\n(higher = faster)", fontsize=14, fontweight="bold",
                 pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=10)

    fig.tight_layout()
    fig.savefig(CHARTS / "radar_comparison.png", format="png", dpi=150)
    plt.close(fig)
    print("  -> charts/radar_comparison.png")


def main():
    CHARTS.mkdir(parents=True, exist_ok=True)
    data = load_data()

    # Load memory data if available
    mem_data = None
    if MEMORY_RESULTS.exists():
        with open(MEMORY_RESULTS) as f:
            mem_data = json.load(f)

    print("Generating charts (xkcd style)...")

    with plt.xkcd(scale=1, length=100, randomness=2):
        plt.rcParams.update({
            "font.size": 11,
            "axes.linewidth": 1.5,
        })
        plot_file_identical(data)
        plot_file_differ_quarter(data)
        plot_file_differ_last(data)
        plot_dir_comparison(data)
        plot_speedup_heatmap(data)
        if mem_data:
            plot_memory_usage(mem_data)
        plot_radar(data, mem_data)

    print("\nDone! Charts saved to benchmarks/charts/")


if __name__ == "__main__":
    main()
