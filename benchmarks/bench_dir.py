#!/usr/bin/env python3
"""Directory comparison benchmarks.

Compares: komparu.compare_dir, filecmp.dircmp, Go -dir, Rust -dir.
Scenarios: 100 files × 1MB (identical/1-differ), 1000 files × 100KB.

Usage:
    python bench_dir.py           # all benchmarks
    python bench_dir.py --fast    # quick run
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from conftest import (
    GO_BIN,
    RESULTS_DIR,
    RUST_BIN,
    cleanup_tmpfs,
    create_test_dirs,
    ensure_competitors,
    ensure_tmpfs,
    warm_page_cache,
)

MB = 1024 ** 2
KB = 1024

WARMUP_RUNS = 2
REPEATS = 10
REPEATS_FAST = 3
MIN_TIME = 1.0  # directory benchmarks are slower, use longer minimum


# ── Benchmark callables ──────────────────────────────────────────────

def bench_komparu_dir(dir_a: str, dir_b: str) -> None:
    import komparu
    komparu.compare_dir(dir_a, dir_b)


def bench_filecmp_dir(dir_a: str, dir_b: str) -> None:
    """Full recursive directory comparison using filecmp."""
    filecmp.clear_cache()

    def _compare_recursive(dcmp: filecmp.dircmp) -> bool:
        if dcmp.left_only or dcmp.right_only:
            return False
        for name in dcmp.common_files:
            if not filecmp.cmp(
                os.path.join(dcmp.left, name),
                os.path.join(dcmp.right, name),
                shallow=False,
            ):
                return False
        for sub_dcmp in dcmp.subdirs.values():
            if not _compare_recursive(sub_dcmp):
                return False
        return True

    dcmp = filecmp.dircmp(dir_a, dir_b)
    _compare_recursive(dcmp)


# ── Timing engine (same as bench_file) ──────────────────────────────

def calibrate_loops(func, args, min_time: float = MIN_TIME) -> int:
    loops = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(loops):
            func(*args)
        elapsed = time.perf_counter() - t0
        if elapsed >= min_time:
            return loops
        loops = max(loops + 1, int(loops * min_time / max(elapsed, 1e-9)))


def time_func(func, args: tuple, repeats: int, warmups: int = WARMUP_RUNS) -> list[float]:
    loops = calibrate_loops(func, args)
    for _ in range(warmups):
        for _ in range(loops):
            func(*args)
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(loops):
            func(*args)
        elapsed = time.perf_counter() - t0
        times.append(elapsed / loops)
    return times


def time_command(cmd: list[str], repeats: int, warmups: int = WARMUP_RUNS) -> list[float]:
    for _ in range(warmups):
        subprocess.run(cmd, capture_output=True)
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
    return times


def compute_stats(times: list[float]) -> dict:
    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min": min(times),
        "max": max(times),
        "samples": len(times),
        "raw": times,
    }


def format_time(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f}us"
    elif seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    else:
        return f"{seconds:.3f}s"


# ── Scenarios ────────────────────────────────────────────────────────

DIR_SCENARIOS = [
    {
        "name": "dir_100x1MB_identical",
        "num_files": 100,
        "file_size": 1 * MB,
        "differ_index": None,
    },
    {
        "name": "dir_100x1MB_1differ",
        "num_files": 100,
        "file_size": 1 * MB,
        "differ_index": 99,
    },
    {
        "name": "dir_1000x100KB_identical",
        "num_files": 1000,
        "file_size": 100 * KB,
        "differ_index": None,
    },
]


def run_benchmarks(fast: bool = False) -> dict:
    ensure_competitors()
    tmpfs = ensure_tmpfs()
    repeats = REPEATS_FAST if fast else REPEATS

    all_results = {}

    for scenario in DIR_SCENARIOS:
        bench_name = scenario["name"]
        print(f"\n{'='*60}")
        print(f"  {bench_name}")
        print(f"{'='*60}")

        data_dir = tmpfs / bench_name
        dir_a, dir_b = create_test_dirs(
            data_dir,
            num_files=scenario["num_files"],
            file_size=scenario["file_size"],
            differ_index=scenario["differ_index"],
        )
        warm_page_cache(dir_a, dir_b)

        da, db = str(dir_a), str(dir_b)
        results = {}

        # Python callables
        for name, func in [
            ("komparu", bench_komparu_dir),
            ("filecmp", bench_filecmp_dir),
        ]:
            print(f"  {name}...", end=" ", flush=True)
            warm_page_cache(dir_a, dir_b)
            times = time_func(func, (da, db), repeats=repeats)
            stats = compute_stats(times)
            results[name] = stats
            print(f"{format_time(stats['median'])} (median)", flush=True)

        # CLI tools
        cli_tools = [
            ("go", [str(GO_BIN), "-dir", da, db]),
            ("rust", [str(RUST_BIN), "-dir", da, db]),
        ]

        for name, cmd in cli_tools:
            print(f"  {name}...", end=" ", flush=True)
            warm_page_cache(dir_a, dir_b)
            times = time_command(cmd, repeats=repeats)
            stats = compute_stats(times)
            results[name] = stats
            print(f"{format_time(stats['median'])} (median)", flush=True)

        all_results[bench_name] = results
        shutil.rmtree(data_dir, ignore_errors=True)

    return all_results


def print_results_table(results: dict) -> str:
    lines = []
    for bench_name, tools in sorted(results.items()):
        lines.append(f"\n### {bench_name}\n")
        lines.append("| Tool | Median | Mean | Stdev | Samples |")
        lines.append("|------|--------|------|-------|---------|")

        sorted_tools = sorted(tools.items(), key=lambda x: x[1]["median"])
        fastest = sorted_tools[0][1]["median"] if sorted_tools else 1

        for name, data in sorted_tools:
            ratio = data["median"] / fastest if fastest > 0 else 1
            suffix = "" if ratio < 1.05 else f" ({ratio:.1f}x)"
            lines.append(
                f"| {name} "
                f"| {format_time(data['median'])}{suffix} "
                f"| {format_time(data['mean'])} "
                f"| {format_time(data['stdev'])} "
                f"| {data['samples']} |"
            )

    table = "\n".join(lines)
    print(table)
    return table


def main():
    parser = argparse.ArgumentParser(description="Directory comparison benchmarks")
    parser.add_argument("--fast", action="store_true", help="Quick run")
    args = parser.parse_args()

    try:
        results = run_benchmarks(fast=args.fast)
        table = print_results_table(results)

        clean = {}
        for bench_name, tools in results.items():
            clean[bench_name] = {}
            for name, data in tools.items():
                clean[bench_name][name] = {k: v for k, v in data.items() if k != "raw"}
        with open(RESULTS_DIR / "dir_results.json", "w") as f:
            json.dump(clean, f, indent=2)

        with open(RESULTS_DIR / "dir_results.md", "w") as f:
            f.write("# Directory Comparison Benchmarks\n\n")
            f.write(table)

        print(f"\nResults saved to {RESULTS_DIR}/dir_results.json")
    finally:
        cleanup_tmpfs()


if __name__ == "__main__":
    main()
