# Memory Usage Benchmarks

## Memory Usage: Peak Heap Allocation

| Size | komparu | filecmp (deep) | filecmp (shallow) | hashlib SHA-256 |
|------|---------|----------------|-------------------|-----------------|
| 100MB | 425 B | 33.2 KB | 837 B | 133.3 KB |
| 10MB | 425 B | 33.2 KB | 836 B | 133.3 KB |
| 1GB | 425 B | 33.2 KB | 835 B | 133.3 KB |
| 1MB | 425 B | 33.2 KB | 835 B | 133.3 KB |

## Memory Usage: Process Peak RSS

| Size | cmp -s | Go | Rust |
|------|--------|----|------|
| 100MB | 2.1 MB | 2.2 MB | 2.2 MB |
| 10MB | 2.2 MB | 2.2 MB | 2.2 MB |
| 1GB | 2.1 MB | 2.2 MB | 2.2 MB |
| 1MB | 1.3 MB | 724.0 KB | 528.0 KB |