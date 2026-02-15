# File Comparison Benchmarks


### file_1MB_identical

| Tool | Median | Mean | Stdev | Min | Max | Samples |
|------|--------|------|-------|-----|-----|---------|
| komparu | 361.2us | 324.0us | 54.0us | 260.5us | 364.9us | 5 |
| filecmp | 371.6us | 373.5us | 9.2us | 361.4us | 385.5us | 5 |
| cmp | 1.42ms (3.9x) | 2.04ms | 979.4us | 1.24ms | 3.23ms | 5 |
| hashlib_sha256 | 2.18ms (6.0x) | 2.25ms | 206.2us | 2.09ms | 2.61ms | 5 |
| rust | 2.62ms (7.2x) | 3.32ms | 1.69ms | 1.83ms | 5.73ms | 5 |
| diff | 4.01ms (11.1x) | 4.57ms | 882.0us | 3.99ms | 6.01ms | 5 |
| go | 5.20ms (14.4x) | 5.09ms | 1.33ms | 3.07ms | 6.69ms | 5 |