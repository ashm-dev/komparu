"""Shared benchmark infrastructure.

Provides test data generation, competitor compilation helpers,
and tmpfs management for fair benchmarking.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Paths
BENCH_DIR = Path(__file__).parent
COMPETITORS_DIR = BENCH_DIR / "competitors"
RESULTS_DIR = BENCH_DIR / "results"

# Competitor binaries
GO_BIN = COMPETITORS_DIR / "compare_go"
RUST_BIN = COMPETITORS_DIR / "compare_rs"

# Use tmpfs to eliminate disk I/O variance
TMPFS_BASE = Path("/dev/shm/komparu_bench")


def ensure_competitors() -> None:
    """Build Go and Rust competitors if not already compiled."""
    if not GO_BIN.exists() or not RUST_BIN.exists():
        subprocess.run(
            ["make", "all"],
            cwd=COMPETITORS_DIR,
            check=True,
            capture_output=True,
        )


def ensure_tmpfs() -> Path:
    """Ensure tmpfs benchmark directory exists."""
    TMPFS_BASE.mkdir(parents=True, exist_ok=True)
    return TMPFS_BASE


def cleanup_tmpfs() -> None:
    """Remove tmpfs benchmark directory."""
    if TMPFS_BASE.exists():
        shutil.rmtree(TMPFS_BASE, ignore_errors=True)


def generate_file(path: Path, size: int) -> None:
    """Generate a file of given size with random data."""
    chunk = 1024 * 1024  # write 1MB at a time
    with open(path, "wb") as f:
        remaining = size
        while remaining > 0:
            n = min(chunk, remaining)
            f.write(os.urandom(n))
            remaining -= n


def create_test_files(
    base: Path,
    size: int,
    scenario: str,
) -> tuple[Path, Path]:
    """Create a pair of test files for benchmarking.

    Scenarios:
        "identical"         — both files byte-identical
        "differ_first"      — first byte differs
        "differ_last"       — last byte differs
        "differ_quarter"    — byte at 25% offset differs (NOT checked by quick_check)
    """
    base.mkdir(parents=True, exist_ok=True)
    file_a = base / "file_a"
    file_b = base / "file_b"

    generate_file(file_a, size)
    shutil.copy2(file_a, file_b)

    if scenario == "differ_first":
        with open(file_b, "r+b") as f:
            first = f.read(1)
            f.seek(0)
            f.write(bytes([(first[0] ^ 0xFF)]))
    elif scenario == "differ_last":
        with open(file_b, "r+b") as f:
            f.seek(-1, 2)
            last = f.read(1)
            f.seek(-1, 2)
            f.write(bytes([(last[0] ^ 0xFF)]))
    elif scenario == "differ_quarter":
        # Flip byte at 25% — quick_check only samples 0%, 50%, 100%
        with open(file_b, "r+b") as f:
            pos = size // 4
            f.seek(pos)
            byte = f.read(1)
            f.seek(pos)
            f.write(bytes([(byte[0] ^ 0xFF)]))

    return file_a, file_b


def create_test_dirs(
    base: Path,
    num_files: int,
    file_size: int,
    differ_index: int | None = None,
) -> tuple[Path, Path]:
    """Create a pair of directories for benchmarking.

    Args:
        base: Parent directory.
        num_files: Number of files per directory.
        file_size: Size of each file in bytes.
        differ_index: If set, file at this index will have last byte flipped.
    """
    dir_a = base / "dir_a"
    dir_b = base / "dir_b"
    dir_a.mkdir(parents=True, exist_ok=True)
    dir_b.mkdir(parents=True, exist_ok=True)

    for i in range(num_files):
        fname = f"file_{i:05d}.bin"
        fa = dir_a / fname
        fb = dir_b / fname
        generate_file(fa, file_size)
        shutil.copy2(fa, fb)

        if differ_index is not None and i == differ_index:
            with open(fb, "r+b") as f:
                f.seek(-1, 2)
                last = f.read(1)
                f.seek(-1, 2)
                f.write(bytes([(last[0] ^ 0xFF)]))

    return dir_a, dir_b


def warm_page_cache(*paths: Path) -> None:
    """Read files to warm page cache before benchmarking."""
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    _ = f.read_bytes()
        elif p.is_file():
            _ = p.read_bytes()


def size_label(size: int) -> str:
    """Human-readable size label."""
    if size >= 1024 ** 3:
        return f"{size // (1024 ** 3)}GB"
    elif size >= 1024 ** 2:
        return f"{size // (1024 ** 2)}MB"
    elif size >= 1024:
        return f"{size // 1024}KB"
    return f"{size}B"
