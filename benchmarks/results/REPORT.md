# komparu Benchmark Report

Generated: 2026-02-15 11:51:05

## File Comparison

| Scenario | Size | komparu | filecmp | hashlib | cmp -s | Go | Rust |
|----------|------|---------|---------|---------|--------|----|------|
| differ_first | 100MB | 19.2us | 9.6us | 143.08ms | 366.9us | 704.3us | 436.4us |
| differ_last | 100MB | 27.0us | 38.77ms | 144.04ms | 35.73ms | 31.23ms | 32.13ms |
| differ_quarter | 100MB | 6.70ms | 9.58ms | 142.79ms | 9.49ms | 8.43ms | 8.66ms |
| identical | 100MB | 30.40ms | 38.44ms | 143.09ms | 35.77ms | 30.89ms | 32.11ms |
| differ_first | 10MB | 19.0us | 9.5us | 14.34ms | 385.2us | 729.6us | 424.2us |
| differ_last | 10MB | 27.1us | 3.79ms | 14.29ms | 4.08ms | 3.91ms | 3.78ms |
| differ_quarter | 10MB | 431.7us | 663.2us | 14.32ms | 1.20ms | 1.44ms | 1.23ms |
| identical | 10MB | 2.29ms | 3.80ms | 14.35ms | 4.05ms | 3.81ms | 3.69ms |
| differ_first | 1GB | 21.7us | 9.8us | 1.452s | 386.6us | 702.2us | 448.9us |
| differ_last | 1GB | 29.8us | 374.81ms | 1.447s | 342.37ms | 294.89ms | 299.09ms |
| differ_quarter | 1GB | 76.77ms | 96.37ms | 1.454s | 89.27ms | 76.82ms | 78.14ms |
| identical | 1GB | 284.23ms | 367.65ms | 1.453s | 335.80ms | 288.05ms | 290.59ms |
| differ_first | 1MB | 17.0us | 9.5us | 1.29ms | 394.5us | 734.0us | 477.5us |
| differ_last | 1MB | 24.5us | 206.4us | 1.28ms | 597.7us | 907.0us | 630.6us |
| differ_quarter | 1MB | 69.7us | 53.5us | 1.29ms | 526.0us | 741.6us | 520.7us |
| identical | 1MB | 157.0us | 210.2us | 1.28ms | 574.7us | 926.0us | 682.8us |

## Directory Comparison

| Scenario | komparu | filecmp | Go | Rust |
|----------|---------|---------|-----|------|
| 1000x100KB_identical | 23.32ms | 54.32ms | 42.54ms | 38.70ms |
| 100x1MB_1differ | 13.07ms | 41.85ms | 33.97ms | 32.90ms |
| 100x1MB_identical | 13.25ms | 41.30ms | 33.67ms | 32.84ms |

## Speedup (komparu vs competitors)

| Scenario | vs filecmp | vs hashlib | vs cmp -s | vs Go | vs Rust |
|----------|-----------|-----------|----------|-------|---------|
| 100MB differ first | 0.5x | 7444.4x | 19.1x | 36.6x | 22.7x |
| 100MB differ last | 1436.6x | 5337.5x | 1323.9x | 1157.4x | 1190.5x |
| 100MB differ quarter | 1.4x | 21.3x | 1.4x | 1.3x | 1.3x |
| 100MB identical | 1.3x | 4.7x | 1.2x | 1.0x | 1.1x |
| 10MB differ first | 0.5x | 754.4x | 20.3x | 38.4x | 22.3x |
| 10MB differ last | 139.8x | 527.1x | 150.4x | 144.1x | 139.2x |
| 10MB differ quarter | 1.5x | 33.2x | 2.8x | 3.3x | 2.9x |
| 10MB identical | 1.7x | 6.3x | 1.8x | 1.7x | 1.6x |
| 1GB differ first | 0.5x | 67037.5x | 17.8x | 32.4x | 20.7x |
| 1GB differ last | 12568.2x | 48516.6x | 11480.4x | 9888.3x | 10029.0x |
| 1GB differ quarter | 1.3x | 18.9x | 1.2x | 1.0x | 1.0x |
| 1GB identical | 1.3x | 5.1x | 1.2x | 1.0x | 1.0x |
| 1MB differ first | 0.6x | 75.9x | 23.2x | 43.2x | 28.1x |
| 1MB differ last | 8.4x | 52.4x | 24.4x | 37.1x | 25.8x |
| 1MB differ quarter | 0.8x | 18.4x | 7.5x | 10.6x | 7.5x |
| 1MB identical | 1.3x | 8.2x | 3.7x | 5.9x | 4.3x |

---

Total benchmark time: 939s

**Methodology:**
- Each benchmark: N repeats x auto-calibrated loops per repeat
- Warmup runs before measurement
- Data on tmpfs (/dev/shm) — no disk I/O variance
- Page cache warmed before each benchmark
- CLI tools (cmp, Go, Rust) include subprocess overhead
