[English](README.md) | **Русский**

# komparu

Сверхбыстрая библиотека сравнения файлов на ядре C23. Побайтовое сравнение локальных файлов, директорий, архивов и HTTP-ресурсов через memory-mapped I/O, векторные операции и нативный пул потоков.

## Возможности

- **mmap + MADV_SEQUENTIAL** — чтение без копирования с подсказками ядру для опережающего чтения
- **Quick check** — выборочная проверка первых/последних/средних байтов перед полным сканированием (ловит большинство различий за O(1))
- **Предпроверка размера** — пропускает сравнение содержимого при различии размеров файлов
- **Параллельное сравнение директорий** — нативный pthread-пул, настраиваемое число воркеров
- **Сравнение архивов** — поэлементное сравнение tar/zip/gz/bz2/xz через libarchive
- **HTTP-сравнение** — сравнение локальных файлов с удалёнными URL через libcurl
- **Async API** — `komparu.aio` с C-пулом потоков + eventfd, без overhead от `asyncio.to_thread()`
- **Защита от архивных бомб** — настраиваемые лимиты размера/степени сжатия/числа записей

## Установка

```bash
pip install komparu
```

Из исходников (требуется clang, cmake, libcurl, libarchive):

```bash
CC=clang CMAKE_ARGS="-DCMAKE_C_COMPILER=clang" pip install -e .
```

## Быстрый старт

```python
import komparu

# Сравнить два файла
equal = komparu.compare("file_a.bin", "file_b.bin")

# Сравнить директории
result = komparu.compare_dir("/dir_a", "/dir_b")
print(result.equal, result.diff, result.only_left, result.only_right)

# Сравнить архивы
result = komparu.compare_archive("a.tar.gz", "b.tar.gz")

# Сравнить файл с URL
equal = komparu.compare("local.bin", "https://example.com/remote.bin")

# Сравнить директорию с набором URL
result = komparu.compare_dir_urls("/local/dir", {
    "file1.txt": "https://cdn.example.com/file1.txt",
    "file2.txt": "https://cdn.example.com/file2.txt",
})

# Проверить идентичность всех источников
all_same = komparu.compare_all(["file1", "file2", "file3"])

# Детальное попарное сравнение
result = komparu.compare_many(["file1", "file2", "file3"])
print(result.all_equal, result.groups, result.diff)
```

## Async API

```python
import komparu.aio

# Все функции повторяют синхронный API
equal = await komparu.aio.compare("file_a", "file_b")
result = await komparu.aio.compare_dir("/dir_a", "/dir_b")
result = await komparu.aio.compare_archive("a.tar.gz", "b.tar.gz")
all_same = await komparu.aio.compare_all(["f1", "f2", "f3"])
result = await komparu.aio.compare_many(["f1", "f2", "f3"])
result = await komparu.aio.compare_dir_urls("/dir", url_map)
```

Async API использует C-потоки + eventfd/pipe, интегрированные с `asyncio.loop.add_reader()`. Без Python-потоков, без борьбы за GIL, без стековых накладных расходов.

## Конфигурация

```python
komparu.configure(
    chunk_size=65536,          # байт на чтение (по умолчанию: 64KB)
    size_precheck=True,        # сначала сравнить размеры
    quick_check=True,          # выборочная проверка первых/последних/средних байтов
    max_workers=0,             # размер пула потоков (0 = авто)
    timeout=30.0,              # HTTP-таймаут в секундах
    follow_redirects=True,     # следовать HTTP-редиректам
    verify_ssl=True,           # проверять SSL-сертификаты
    headers={"Authorization": "Bearer ..."},  # HTTP-заголовки
)
```

## Типы

```python
from komparu import DirResult, CompareResult, DiffReason, Source

# DirResult — возвращается compare_dir, compare_archive, compare_dir_urls
result.equal         # bool
result.diff          # dict[str, DiffReason] — относительные пути с различиями
result.only_left     # set[str] — файлы только в первом источнике
result.only_right    # set[str] — файлы только во втором источнике

# DiffReason — причина различия
DiffReason.CONTENT_MISMATCH   # содержимое не совпадает
DiffReason.SIZE_MISMATCH      # размеры не совпадают
DiffReason.MISSING            # файл отсутствует
DiffReason.TYPE_MISMATCH      # разные типы (файл vs директория)
DiffReason.READ_ERROR         # ошибка чтения

# CompareResult — возвращается compare_many
result.all_equal     # bool
result.groups        # list[set[str]] — группы идентичных источников
result.diff          # dict[tuple[str, str], bool] — попарные результаты

# Source — для индивидуальных HTTP-настроек
source = Source(url="https://...", headers={...}, timeout=10.0)
komparu.compare(source, "local.bin")
```

## Бенчмарки

Все бенчмарки на tmpfs (/dev/shm) с прогретым page cache. 20 замеров на бенчмарк, автокалибровка числа итераций. Конкуренты: Python `filecmp` (stdlib), `hashlib` SHA-256, POSIX `cmp -s`, GNU `diff -q`, Go 1.25, Rust 1.93. Исходный код и сырые результаты в [`benchmarks/`](benchmarks/).

### Сравнение файлов: идентичные

<p align="center">
  <img src="benchmarks/charts/file_identical.png" width="700" alt="Бенчмарк идентичных файлов">
</p>

komparu стабильно внизу (быстрее всех). Для идентичных файлов он в **1.3x быстрее** filecmp (stdlib Python) и на уровне нативных реализаций Go/Rust.

### Сравнение файлов: различие на 25% (честное последовательное сканирование)

<p align="center">
  <img src="benchmarks/charts/file_differ_quarter.png" width="700" alt="Бенчмарк различия на 25%">
</p>

Самое честное сравнение: различие на позиции 25% файла, которую **quick_check НЕ проверяет**. komparu выполняет реальное последовательное mmap+memcmp сканирование, показывая чистое преимущество I/O-движка без каких-либо обходных путей.

### Сравнение файлов: различие в последнем байте (Quick Check)

<p align="center">
  <img src="benchmarks/charts/file_differ_last.png" width="700" alt="Бенчмарк различия в последнем байте">
</p>

**quick_check** в komparu проверяет первые/последние/средние байты до полного сканирования. Это позволяет мгновенно обнаружить различие в конце файла (**30us для 1GB**), пока все конкуренты вынуждены прочитать файл целиком. Плоская красная линия — O(1) вне зависимости от размера файла.

### Сравнение директорий

<p align="center">
  <img src="benchmarks/charts/dir_comparison.png" width="700" alt="Бенчмарк сравнения директорий">
</p>

Нативный пул потоков komparu даёт ускорение в **2-3x** по сравнению с filecmp и обгоняет реализации на Go/Rust во всех сценариях.

### Потребление памяти

<p align="center">
  <img src="benchmarks/charts/memory_usage.png" width="700" alt="Бенчмарк потребления памяти">
</p>

komparu аллоцирует всего **425 байт** Python-кучи вне зависимости от размера файла (mmap-страницы управляются ядром). filecmp требует 33KB (буферы 8KB x2), hashlib — 133KB (контекст SHA-256 + буфер). Примечание: `filecmp shallow=True` проверяет только stat файла, не содержимое.

### Многомерное сравнение

<p align="center">
  <img src="benchmarks/charts/radar_comparison.png" width="600" alt="Радарное сравнение">
</p>

### Тепловая карта ускорения

<p align="center">
  <img src="benchmarks/charts/speedup_heatmap.png" width="650" alt="Тепловая карта ускорения">
</p>

Зелёный = komparu быстрее. Тёмно-зелёные ячейки в строках `differ_last` показывают преимущество quick_check. Сравните со строками `differ_quarter` для честной последовательной производительности.

<details>
<summary>Сырые числа (медиана)</summary>

**Сравнение файлов**

| Сценарий | Размер | komparu | filecmp | cmp -s | Go | Rust |
|----------|--------|---------|---------|--------|----|------|
| идентичные | 1MB | 157us | 210us | 575us | 926us | 683us |
| идентичные | 10MB | 2.29ms | 3.80ms | 4.05ms | 3.81ms | 3.69ms |
| идентичные | 100MB | 30ms | 38ms | 36ms | 31ms | 32ms |
| идентичные | 1GB | 284ms | 368ms | 336ms | 288ms | 291ms |
| различие на 25% | 1MB | 70us | 54us | 526us | 742us | 521us |
| различие на 25% | 10MB | 432us | 663us | 1.20ms | 1.44ms | 1.23ms |
| различие на 25% | 100MB | 6.7ms | 9.6ms | 9.5ms | 8.4ms | 8.7ms |
| различие на 25% | 1GB | 77ms | 96ms | 89ms | 77ms | 78ms |
| различие в конце | 1MB | 25us | 206us | 598us | 907us | 631us |
| различие в конце | 10MB | 27us | 3.79ms | 4.08ms | 3.91ms | 3.78ms |
| различие в конце | 100MB | 27us | 39ms | 36ms | 31ms | 32ms |
| различие в конце | 1GB | 30us | 375ms | 342ms | 295ms | 299ms |

**Сравнение директорий**

| Сценарий | komparu | filecmp | Go | Rust |
|----------|---------|---------|-----|------|
| 100 файлов x 1MB, идентичные | 13ms | 41ms | 34ms | 33ms |
| 100 файлов x 1MB, 1 отличается | 13ms | 42ms | 34ms | 33ms |
| 1000 файлов x 100KB, идентичные | 23ms | 54ms | 43ms | 39ms |

**Память (аллокация Python-кучи)**

| Размер | komparu | filecmp (deep) | filecmp (shallow) | hashlib SHA-256 |
|--------|---------|----------------|-------------------|-----------------|
| 1MB-1GB | 425 B | 33.2 KB | 835 B | 133.3 KB |

</details>

### Воспроизведение

```bash
cd benchmarks/competitors && make all && cd ..
python run_all.py --fast   # ~5 мин быстрый прогон
python run_all.py          # ~30 мин полный прогон
```

Методология описана в [`benchmarks/README.md`](benchmarks/README.md).

## Архитектура

Ядро на C23 с Python-биндингами через CPython C API:

- **mmap** с `MADV_SEQUENTIAL` для оптимального упреждающего чтения
- **pthread-пул** для параллельного сравнения директорий и множества файлов
- **eventfd** (Linux) / **pipe** (macOS) для асинхронных уведомлений
- **libcurl** для HTTP с пулом соединений
- **libarchive** для поддержки форматов архивов
- **CAS-based жизненный цикл задач** для безопасной асинхронной отмены

## Документация

- [API-справочник](docs/ru/api.md)
- [Архитектура](docs/ru/architecture.md)
- [Требования](docs/ru/requirements.md)
- [Безопасность](docs/ru/security.md)
- [Краевые случаи](docs/ru/edge-cases.md)
- [План работ](docs/ru/workplan.md)

## Лицензия

MIT
