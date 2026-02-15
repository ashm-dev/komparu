#!/usr/bin/env python3
"""Run all komparu benchmarks and produce a combined report.

Usage:
    python run_all.py           # full suite
    python run_all.py --fast    # quick run (fewer iterations)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from conftest import RESULTS_DIR, cleanup_tmpfs, ensure_competitors, ensure_tmpfs

import bench_file
import bench_dir
import bench_memory


def format_time(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f}us"
    elif seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    else:
        return f"{seconds:.3f}s"


def build_summary_table(file_results: dict, dir_results: dict) -> str:
    """Build a single summary markdown table for README."""
    lines = []

    # ── File benchmarks: compact table ──
    lines.append("## File Comparison\n")
    lines.append("| Scenario | Size | komparu | filecmp | hashlib | cmp -s | Go | Rust |")
    lines.append("|----------|------|---------|---------|---------|--------|----|------|")

    for bench_name in sorted(file_results.keys()):
        tools = file_results[bench_name]
        parts = bench_name.split("_")
        size = parts[1]
        scenario = "_".join(parts[2:])

        row = [scenario, size]
        for tool in ["komparu", "filecmp", "hashlib_sha256", "cmp", "go", "rust"]:
            if tool in tools:
                row.append(format_time(tools[tool]["median"]))
            else:
                row.append("-")

        lines.append("| " + " | ".join(row) + " |")

    # ── Directory benchmarks ──
    lines.append("\n## Directory Comparison\n")
    lines.append("| Scenario | komparu | filecmp | Go | Rust |")
    lines.append("|----------|---------|---------|-----|------|")

    for bench_name in sorted(dir_results.keys()):
        tools = dir_results[bench_name]
        label = bench_name.replace("dir_", "")
        row = [label]
        for tool in ["komparu", "filecmp", "go", "rust"]:
            if tool in tools:
                row.append(format_time(tools[tool]["median"]))
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    # ── Speedup summary ──
    lines.append("\n## Speedup (komparu vs competitors)\n")
    lines.append("| Scenario | vs filecmp | vs hashlib | vs cmp -s | vs Go | vs Rust |")
    lines.append("|----------|-----------|-----------|----------|-------|---------|")

    for bench_name in sorted(file_results.keys()):
        tools = file_results[bench_name]
        if "komparu" not in tools:
            continue
        komparu_t = tools["komparu"]["median"]
        parts = bench_name.split("_")
        label = f"{parts[1]} {' '.join(parts[2:])}"

        row = [label]
        for rival in ["filecmp", "hashlib_sha256", "cmp", "go", "rust"]:
            if rival in tools and komparu_t > 0:
                speedup = tools[rival]["median"] / komparu_t
                row.append(f"{speedup:.1f}x")
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run all komparu benchmarks")
    parser.add_argument("--fast", action="store_true", help="Quick run")
    args = parser.parse_args()

    start = time.time()
    print("=" * 60)
    print("  komparu benchmark suite")
    print("=" * 60)

    ensure_competitors()
    ensure_tmpfs()

    try:
        # File benchmarks
        print("\n\n>>> FILE BENCHMARKS <<<\n")
        file_results = bench_file.run_benchmarks(
            bench_file.SIZES, bench_file.SCENARIOS, fast=args.fast,
        )

        # Directory benchmarks
        print("\n\n>>> DIRECTORY BENCHMARKS <<<\n")
        dir_results = bench_dir.run_benchmarks(fast=args.fast)

        # Memory benchmarks
        print("\n\n>>> MEMORY BENCHMARKS <<<\n")
        mem_results = bench_memory.run_benchmarks(fast=args.fast)

        # Combined report
        print("\n\n>>> COMBINED REPORT <<<\n")
        summary = build_summary_table(file_results, dir_results)
        print(summary)

        # Save all
        combined = RESULTS_DIR / "all_results.json"
        all_data = {"file": {}, "dir": {}}
        for bench_name, tools in file_results.items():
            all_data["file"][bench_name] = {
                name: {k: v for k, v in data.items() if k != "raw"}
                for name, data in tools.items()
            }
        for bench_name, tools in dir_results.items():
            all_data["dir"][bench_name] = {
                name: {k: v for k, v in data.items() if k != "raw"}
                for name, data in tools.items()
            }
        with open(combined, "w") as f:
            json.dump(all_data, f, indent=2)

        report = RESULTS_DIR / "REPORT.md"
        with open(report, "w") as f:
            f.write("# komparu Benchmark Report\n\n")
            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(summary)
            f.write("\n\n---\n\n")
            f.write(f"Total benchmark time: {time.time() - start:.0f}s\n\n")
            f.write("**Methodology:**\n")
            f.write("- Each benchmark: N repeats x auto-calibrated loops per repeat\n")
            f.write("- Warmup runs before measurement\n")
            f.write("- Data on tmpfs (/dev/shm) — no disk I/O variance\n")
            f.write("- Page cache warmed before each benchmark\n")
            f.write("- CLI tools (cmp, Go, Rust) include subprocess overhead\n")

        print(f"\n\nAll results: {combined}")
        print(f"Report: {report}")
        print(f"Total time: {time.time() - start:.0f}s")

    finally:
        cleanup_tmpfs()


if __name__ == "__main__":
    main()
