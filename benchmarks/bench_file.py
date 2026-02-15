#!/usr/bin/env python3
"""Single file comparison benchmarks.

Compares: komparu, filecmp, hashlib (SHA-256), cmp -s, diff -q, Go, Rust.
Scenarios: identical, differ-first-byte, differ-last-byte.
Sizes: 1MB, 10MB, 100MB, 1GB.

Statistical methodology:
  - Each benchmark: REPEATS runs × auto-calibrated LOOPS per run
  - Warmup runs before measurement
  - Reports: mean, median, stdev, min, max (per-call time)
  - Data on tmpfs (/dev/shm) — no disk I/O variance
  - Page cache warmed before each benchmark

Usage:
    python bench_file.py                       # all benchmarks
    python bench_file.py --size 10MB           # specific size
    python bench_file.py --scenario identical  # specific scenario
    python bench_file.py --fast                # quick run
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

from conftest import (
    GO_BIN,
    RESULTS_DIR,
    RUST_BIN,
    cleanup_tmpfs,
    create_test_files,
    ensure_competitors,
    ensure_tmpfs,
    size_label,
    warm_page_cache,
)

MB = 1024 ** 2
GB = 1024 ** 3

SIZES = {
    "1MB": 1 * MB,
    "10MB": 10 * MB,
    "100MB": 100 * MB,
    "1GB": 1 * GB,
}

SCENARIOS = ["identical", "differ_first", "differ_last", "differ_quarter"]

WARMUP_RUNS = 3
REPEATS = 20        # number of timed samples
REPEATS_FAST = 5
MIN_TIME = 0.5      # calibrate loops so each repeat takes >= this many seconds


# ── Benchmark callables ──────────────────────────────────────────────

def bench_komparu(file_a: str, file_b: str) -> None:
    import komparu
    komparu.compare(file_a, file_b)


def bench_filecmp(file_a: str, file_b: str) -> None:
    filecmp.clear_cache()
    filecmp.cmp(file_a, file_b, shallow=False)


def bench_hashlib(file_a: str, file_b: str) -> None:
    def sha256(path: str) -> bytes:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.digest()
    sha256(file_a) == sha256(file_b)


# ── Timing engine ────────────────────────────────────────────────────

def calibrate_loops(func, args, min_time: float = MIN_TIME) -> int:
    """Find number of loops so one repeat takes >= min_time seconds."""
    loops = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(loops):
            func(*args)
        elapsed = time.perf_counter() - t0
        if elapsed >= min_time:
            return loops
        loops = max(loops + 1, int(loops * min_time / max(elapsed, 1e-9)))


def time_func(
    func,
    args: tuple,
    repeats: int = REPEATS,
    warmups: int = WARMUP_RUNS,
) -> list[float]:
    """Time a function, return list of per-call times in seconds."""
    loops = calibrate_loops(func, args)

    # Warmup
    for _ in range(warmups):
        for _ in range(loops):
            func(*args)

    # Measure
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for _ in range(loops):
            func(*args)
        elapsed = time.perf_counter() - t0
        times.append(elapsed / loops)

    return times


def time_command(
    cmd: list[str],
    repeats: int = REPEATS,
    warmups: int = WARMUP_RUNS,
) -> list[float]:
    """Time a subprocess command, return list of per-call times."""
    # Warmup
    for _ in range(warmups):
        subprocess.run(cmd, capture_output=True)

    # Measure
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)

    return times


def compute_stats(times: list[float]) -> dict:
    """Compute statistical summary."""
    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min": min(times),
        "max": max(times),
        "samples": len(times),
        "raw": times,
    }


# ── Main ─────────────────────────────────────────────────────────────

def run_benchmarks(
    sizes: dict[str, int],
    scenarios: list[str],
    fast: bool = False,
) -> dict:
    """Run all file benchmarks, return results dict."""
    ensure_competitors()
    tmpfs = ensure_tmpfs()
    repeats = REPEATS_FAST if fast else REPEATS

    all_results = {}

    for size_name, size_bytes in sizes.items():
        for scenario in scenarios:
            bench_name = f"file_{size_name}_{scenario}"
            print(f"\n{'='*60}")
            print(f"  {bench_name}")
            print(f"{'='*60}")

            data_dir = tmpfs / bench_name
            file_a, file_b = create_test_files(data_dir, size_bytes, scenario)
            warm_page_cache(file_a, file_b)

            fa, fb = str(file_a), str(file_b)
            results = {}

            # ── Python callables ──
            for name, func in [
                ("komparu", bench_komparu),
                ("filecmp", bench_filecmp),
                ("hashlib_sha256", bench_hashlib),
            ]:
                print(f"  {name}...", end=" ", flush=True)
                warm_page_cache(file_a, file_b)
                times = time_func(func, (fa, fb), repeats=repeats)
                stats = compute_stats(times)
                results[name] = stats
                print(f"{format_time(stats['median'])} (median)", flush=True)

            # ── CLI tools ──
            cli_tools = [
                ("cmp", ["cmp", "-s", fa, fb]),
                ("diff", ["diff", "-q", fa, fb]),
                ("go", [str(GO_BIN), fa, fb]),
                ("rust", [str(RUST_BIN), fa, fb]),
            ]

            for name, cmd in cli_tools:
                print(f"  {name}...", end=" ", flush=True)
                warm_page_cache(file_a, file_b)
                times = time_command(cmd, repeats=repeats)
                stats = compute_stats(times)
                results[name] = stats
                print(f"{format_time(stats['median'])} (median)", flush=True)

            all_results[bench_name] = results
            shutil.rmtree(data_dir, ignore_errors=True)

    return all_results


def format_time(seconds: float) -> str:
    """Format time in human-readable units."""
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.1f}us"
    elif seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    else:
        return f"{seconds:.3f}s"


def print_results_table(results: dict) -> str:
    """Print markdown table of results."""
    lines = []
    for bench_name, tools in sorted(results.items()):
        lines.append(f"\n### {bench_name}\n")
        lines.append("| Tool | Median | Mean | Stdev | Min | Max | Samples |")
        lines.append("|------|--------|------|-------|-----|-----|---------|")

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
                f"| {format_time(data['min'])} "
                f"| {format_time(data['max'])} "
                f"| {data['samples']} |"
            )

    table = "\n".join(lines)
    print(table)
    return table


def save_results(results: dict) -> None:
    """Save results as JSON (without raw arrays for readability)."""
    clean = {}
    for bench_name, tools in results.items():
        clean[bench_name] = {}
        for name, data in tools.items():
            clean[bench_name][name] = {k: v for k, v in data.items() if k != "raw"}
    with open(RESULTS_DIR / "file_results.json", "w") as f:
        json.dump(clean, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="File comparison benchmarks")
    parser.add_argument("--size", choices=list(SIZES.keys()), help="Run only this size")
    parser.add_argument("--scenario", choices=SCENARIOS, help="Run only this scenario")
    parser.add_argument("--fast", action="store_true", help="Quick run")
    args = parser.parse_args()

    sizes = {args.size: SIZES[args.size]} if args.size else SIZES
    scenarios = [args.scenario] if args.scenario else SCENARIOS

    try:
        results = run_benchmarks(sizes, scenarios, fast=args.fast)
        table = print_results_table(results)

        save_results(results)
        with open(RESULTS_DIR / "file_results.md", "w") as f:
            f.write("# File Comparison Benchmarks\n\n")
            f.write(table)

        print(f"\nResults saved to {RESULTS_DIR}/file_results.json")
    finally:
        cleanup_tmpfs()


if __name__ == "__main__":
    main()
