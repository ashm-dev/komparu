# komparu Benchmarks

Statistically rigorous benchmarks comparing komparu against file comparison tools across multiple ecosystems.

## Competitors

| Tool | Language | I/O Strategy | Chunk Size |
|------|----------|-------------|-----------|
| **komparu** | C23 (Python ext) | mmap + MADV_SEQUENTIAL | 64KB |
| filecmp.cmp | Python (stdlib) | buffered read | 8KB |
| hashlib SHA-256 | Python (stdlib) | hash-then-compare | 64KB |
| cmp -s | C (POSIX) | buffered byte compare | varies |
| diff -q | C (GNU) | line-oriented | varies |
| Go comparator | Go 1.25 | os.File.Read | 64KB |
| Rust comparator | Rust 1.93 | std::fs::File::read | 64KB |

## Fairness

- **Same chunk size**: Go and Rust competitors use 64KB buffers (same as komparu default)
- **No mmap handicap**: Go/Rust use standard read() — represents typical real-world code
- **tmpfs data**: All test files in /dev/shm to eliminate disk I/O variance
- **Page cache warm**: All files read into cache before measurement begins
- **Statistical rigor**: 20 samples per benchmark, auto-calibrated loops, warmup runs
- **Open source**: All competitor source code included in `competitors/`
- **Subprocess overhead**: CLI tools (cmp, diff, Go, Rust) measured via subprocess; this is documented as a caveat

## Methodology

Custom timing harness with statistical rigor:

- **Python functions**: `time.perf_counter()` with auto-calibrated loop count (>= 0.5s per repeat)
- **CLI/compiled tools**: `subprocess.run()` with `time.perf_counter()` per invocation
- **Warmup**: 3 runs before measurement (2 for directory benchmarks)
- **Samples**: 20 per benchmark (5 in --fast mode)
- **Statistics**: mean, median, stdev, min, max reported
- **Charts**: matplotlib xkcd style (`gen_charts.py`)

## Running

```bash
# Build competitors
cd benchmarks/competitors && make all && cd ..

# Full suite (~30 minutes)
python run_all.py

# Quick validation (~5 minutes)
python run_all.py --fast

# Individual benchmarks
python bench_file.py --fast
python bench_file.py --size 10MB --scenario identical
python bench_dir.py --fast

# Regenerate charts
python gen_charts.py
```

## Results

JSON results are saved to `results/` for independent verification.

## Test Scenarios

### File Comparison
- **identical**: Both files byte-identical (worst case for comparison — must read everything)
- **differ_first**: First byte differs (best case — early exit)
- **differ_quarter**: Byte at 25% offset differs (quick_check misses it — honest sequential scan)
- **differ_last**: Last byte differs (quick_check catches it — O(1) for komparu)
- **Sizes**: 1MB, 10MB, 100MB, 1GB

### Directory Comparison
- **100 files × 1MB, identical**: All files byte-identical
- **100 files × 1MB, 1 differs**: Last file has last byte flipped
- **1000 files × 100KB, identical**: Stress test with many files

## Understanding the Results

### Why komparu is fast on "differ_last" scenarios
komparu uses a **quick_check** strategy that samples the first, last, and middle
bytes of each file before doing a full sequential comparison. This means it can
detect many differences in O(1) time instead of O(n). This is a real optimization
that benefits real-world workloads — most file changes modify the end of the file
(e.g., appended data, updated timestamps in binary formats).

Other tools (filecmp, cmp, Go, Rust) read files sequentially from the beginning,
so they must read the entire file to find a difference at the end.

### Why "differ_quarter" is the honest comparison
The **differ_quarter** scenario places the difference at 25% of the file — a position
that quick_check does NOT sample (it only checks 0%, 50%, 100%). This forces komparu
into a full sequential mmap+memcmp scan, showing its raw I/O performance without
any shortcut. This is the fairest apples-to-apples comparison of I/O engines.

### Why filecmp is faster on "differ_first" for small files
filecmp uses a simple buffered read with minimal setup overhead. For very small
files where the first byte differs, filecmp's lower per-call overhead gives it
an edge. komparu's mmap setup and size precheck add a small constant cost that
is amortized on larger files.

### CLI tool overhead
cmp, diff, Go, and Rust benchmarks include subprocess creation overhead (~0.5-3ms).
For fair comparison of raw I/O performance, focus on Python-callable benchmarks
(komparu vs filecmp vs hashlib) or large file sizes where overhead is negligible.
