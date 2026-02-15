#!/usr/bin/env python3
"""Memory usage benchmarks for file comparison tools.

Measures peak RSS (Resident Set Size) during file comparison.
komparu uses mmap (kernel-managed pages, minimal user-space RSS)
while filecmp/hashlib use user-space buffers.

For Python callables: tracemalloc measures Python heap allocations.
For CLI tools: /proc/[pid]/status VmHWM (high-water mark RSS).

Usage:
    python bench_memory.py             # all sizes
    python bench_memory.py --fast      # quick run (skip 1GB)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tracemalloc
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

SIZES_FAST = {
    "1MB": 1 * MB,
    "10MB": 10 * MB,
    "100MB": 100 * MB,
}

SAMPLES = 1  # memory is deterministic, one measurement is sufficient


def measure_python_memory(func, args, samples: int = SAMPLES) -> dict:
    """Measure peak Python heap allocation for a callable via tracemalloc."""
    peak_tracemalloc_list = []

    for _ in range(samples):
        tracemalloc.start()
        func(*args)
        _, peak_traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_tracemalloc_list.append(peak_traced)

    return {
        "peak_heap_bytes": max(peak_tracemalloc_list),
    }


def _read_proc_status_vmhwm(pid: int) -> int:
    """Read VmHWM (peak RSS) from /proc/PID/status. Returns bytes."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024  # kB -> bytes
    except (FileNotFoundError, ProcessLookupError):
        pass
    return 0


def _read_proc_status_vmrss(pid: int) -> int:
    """Read VmRSS (current RSS) from /proc/PID/status. Returns bytes."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, ProcessLookupError):
        pass
    return 0


def measure_command_memory(cmd: list[str], samples: int = SAMPLES) -> dict:
    """Measure peak RSS for a subprocess by polling /proc/PID/status."""
    import threading
    import time

    peak_rss_list = []

    for _ in range(samples):
        peak_rss = 0
        stop_event = threading.Event()

        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def monitor():
            nonlocal peak_rss
            while not stop_event.is_set():
                rss = _read_proc_status_vmrss(proc.pid)
                if rss > peak_rss:
                    peak_rss = rss
                time.sleep(0.001)  # 1ms polling
            # Final check
            hwm = _read_proc_status_vmhwm(proc.pid)
            if hwm > peak_rss:
                peak_rss = hwm

        t = threading.Thread(target=monitor, daemon=True)
        t.start()
        proc.wait()
        # Read VmHWM before process zombie reaping
        hwm = _read_proc_status_vmhwm(proc.pid)
        if hwm > peak_rss:
            peak_rss = hwm
        stop_event.set()
        t.join(timeout=1)

        if peak_rss > 0:
            peak_rss_list.append(peak_rss)

    if not peak_rss_list:
        return {"peak_rss_bytes": 0}

    return {
        "peak_rss_bytes": max(peak_rss_list),
    }


def fmt_bytes(n: int) -> str:
    """Format bytes in human-readable form."""
    if n >= GB:
        return f"{n / GB:.2f} GB"
    elif n >= MB:
        return f"{n / MB:.1f} MB"
    elif n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def bench_komparu(file_a: str, file_b: str) -> None:
    import komparu
    komparu.compare(file_a, file_b)


def bench_filecmp_deep(file_a: str, file_b: str) -> None:
    import filecmp
    filecmp.clear_cache()
    filecmp.cmp(file_a, file_b, shallow=False)


def bench_filecmp_shallow(file_a: str, file_b: str) -> None:
    import filecmp
    filecmp.clear_cache()
    filecmp.cmp(file_a, file_b, shallow=True)


def bench_hashlib(file_a: str, file_b: str) -> None:
    import hashlib
    def sha256(path: str) -> bytes:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.digest()
    sha256(file_a) == sha256(file_b)


def run_benchmarks(fast: bool = False) -> dict:
    ensure_competitors()
    tmpfs = ensure_tmpfs()
    sizes = SIZES_FAST if fast else SIZES

    all_results = {}

    for size_name, size_bytes in sizes.items():
        bench_name = f"memory_{size_name}_identical"
        print(f"\n{'='*60}")
        print(f"  {bench_name}")
        print(f"{'='*60}")

        data_dir = tmpfs / bench_name
        file_a, file_b = create_test_files(data_dir, size_bytes, "identical")
        warm_page_cache(file_a, file_b)

        fa, fb = str(file_a), str(file_b)
        results = {}

        # Python callables — tracemalloc + RSS
        python_tools = [
            ("komparu", bench_komparu),
            ("filecmp (deep)", bench_filecmp_deep),
            ("filecmp (shallow)", bench_filecmp_shallow),
            ("hashlib SHA-256", bench_hashlib),
        ]

        for name, func in python_tools:
            print(f"  {name}...", end=" ", flush=True)
            # Warmup: ensure module is imported and code paths exercised
            func(fa, fb)
            warm_page_cache(file_a, file_b)
            mem = measure_python_memory(func, (fa, fb))
            results[name] = mem
            print(f"heap={fmt_bytes(mem['peak_heap_bytes'])}", flush=True)

        # CLI tools — /usr/bin/time peak RSS
        cli_tools = [
            ("cmp -s", ["cmp", "-s", fa, fb]),
            ("Go", [str(GO_BIN), fa, fb]),
            ("Rust", [str(RUST_BIN), fa, fb]),
        ]

        for name, cmd in cli_tools:
            print(f"  {name}...", end=" ", flush=True)
            warm_page_cache(file_a, file_b)
            mem = measure_command_memory(cmd)
            results[name] = mem
            print(f"RSS={fmt_bytes(mem['peak_rss_bytes'])}", flush=True)

        all_results[bench_name] = results
        shutil.rmtree(data_dir, ignore_errors=True)

    return all_results


def print_results_table(results: dict) -> str:
    lines = []
    lines.append("## Memory Usage: Peak Heap Allocation\n")
    lines.append("| Size | komparu | filecmp (deep) | filecmp (shallow) | hashlib SHA-256 |")
    lines.append("|------|---------|----------------|-------------------|-----------------|")

    for bench_name in sorted(results.keys()):
        tools = results[bench_name]
        size = bench_name.split("_")[1]
        row = [size]
        for tool in ["komparu", "filecmp (deep)", "filecmp (shallow)", "hashlib SHA-256"]:
            if tool in tools and "peak_heap_bytes" in tools[tool]:
                row.append(fmt_bytes(tools[tool]["peak_heap_bytes"]))
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("\n## Memory Usage: Process Peak RSS\n")
    lines.append("| Size | cmp -s | Go | Rust |")
    lines.append("|------|--------|----|------|")

    for bench_name in sorted(results.keys()):
        tools = results[bench_name]
        size = bench_name.split("_")[1]
        row = [size]
        for tool in ["cmp -s", "Go", "Rust"]:
            if tool in tools:
                row.append(fmt_bytes(tools[tool]["peak_rss_bytes"]))
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    table = "\n".join(lines)
    print(table)
    return table


def main():
    parser = argparse.ArgumentParser(description="Memory usage benchmarks")
    parser.add_argument("--fast", action="store_true", help="Skip 1GB")
    args = parser.parse_args()

    try:
        results = run_benchmarks(fast=args.fast)
        table = print_results_table(results)

        with open(RESULTS_DIR / "memory_results.json", "w") as f:
            json.dump(results, f, indent=2)

        with open(RESULTS_DIR / "memory_results.md", "w") as f:
            f.write("# Memory Usage Benchmarks\n\n")
            f.write(table)

        print(f"\nResults saved to {RESULTS_DIR}/memory_results.json")
    finally:
        cleanup_tmpfs()


if __name__ == "__main__":
    main()
