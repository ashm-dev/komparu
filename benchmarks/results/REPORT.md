# komparu Benchmark Report

Generated: 2026-02-15 10:37:28

## File Comparison

| Scenario | Size | komparu | filecmp | hashlib | cmp -s | Go | Rust |
|----------|------|---------|---------|---------|--------|----|------|
| differ_first | 100MB | 34.4us | 23.8us | 235.40ms | 3.10ms | 5.98ms | 974.3us |
| differ_last | 100MB | 46.0us | 58.13ms | 174.19ms | 36.28ms | 31.24ms | 31.71ms |
| identical | 100MB | 41.37ms | 56.99ms | 234.61ms | 80.36ms | 36.18ms | 43.77ms |
| differ_first | 10MB | 30.4us | 18.5us | 21.61ms | 689.6us | 1.46ms | 923.3us |
| differ_last | 10MB | 46.1us | 5.89ms | 17.88ms | 6.47ms | 5.97ms | 5.77ms |
| identical | 10MB | 5.12ms | 5.53ms | 22.97ms | 6.82ms | 6.76ms | 11.45ms |
| differ_first | 1GB | 22.1us | 10.0us | 1.454s | 355.9us | 743.6us | 457.1us |
| differ_last | 1GB | 30.1us | 373.39ms | 1.438s | 346.31ms | 295.47ms | 303.40ms |
| identical | 1GB | 285.03ms | 378.72ms | 1.469s | 340.96ms | 291.31ms | 301.55ms |
| differ_first | 1MB | 37.3us | 21.5us | 2.53ms | 710.5us | 6.19ms | 2.97ms |
| differ_last | 1MB | 52.5us | 441.1us | 2.68ms | 1.03ms | 1.17ms | 1.01ms |
| identical | 1MB | 309.7us | 452.6us | 2.43ms | 1.45ms | 2.22ms | 2.05ms |

## Directory Comparison

| Scenario | komparu | filecmp | Go | Rust |
|----------|---------|---------|-----|------|
| 1000x100KB_identical | 23.56ms | 53.84ms | 42.39ms | 37.93ms |
| 100x1MB_1differ | 14.12ms | 41.32ms | 35.52ms | 36.58ms |
| 100x1MB_identical | 14.01ms | 41.54ms | 34.06ms | 32.36ms |

## Speedup (komparu vs competitors)

| Scenario | vs filecmp | vs hashlib | vs cmp -s | vs Go | vs Rust |
|----------|-----------|-----------|----------|-------|---------|
| 100MB differ first | 0.7x | 6834.9x | 90.0x | 173.6x | 28.3x |
| 100MB differ last | 1264.5x | 3789.0x | 789.1x | 679.5x | 689.7x |
| 100MB identical | 1.4x | 5.7x | 1.9x | 0.9x | 1.1x |
| 10MB differ first | 0.6x | 711.4x | 22.7x | 48.2x | 30.4x |
| 10MB differ last | 127.8x | 388.0x | 140.4x | 129.7x | 125.2x |
| 10MB identical | 1.1x | 4.5x | 1.3x | 1.3x | 2.2x |
| 1GB differ first | 0.5x | 65911.9x | 16.1x | 33.7x | 20.7x |
| 1GB differ last | 12420.9x | 47851.2x | 11520.0x | 9829.0x | 10092.8x |
| 1GB identical | 1.3x | 5.2x | 1.2x | 1.0x | 1.1x |
| 1MB differ first | 0.6x | 67.9x | 19.1x | 166.1x | 79.6x |
| 1MB differ last | 8.4x | 51.0x | 19.6x | 22.3x | 19.3x |
| 1MB identical | 1.5x | 7.8x | 4.7x | 7.2x | 6.6x |

---

Total benchmark time: 335s

**Methodology:**
- Each benchmark: N repeats x auto-calibrated loops per repeat
- Warmup runs before measurement
- Data on tmpfs (/dev/shm) — no disk I/O variance
- Page cache warmed before each benchmark
- CLI tools (cmp, Go, Rust) include subprocess overhead
