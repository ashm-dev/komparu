# komparu — Справка по API

## Установка

```bash
pip install komparu
```

## Тип Source

Источники передаются как строки или как объекты `Source`.

- **Строка** — использует глобальные HTTP-настройки из параметров функции
- **`Source()`** — индивидуальная HTTP-конфигурация, приоритет выше глобальной

```python
from komparu import Source

# Строки — глобальные заголовки
komparu.compare("https://a.com/f", "https://b.com/f", headers={"Auth": "token"})

# Source() — свои заголовки для каждого URL
komparu.compare(
    Source("https://s3.aws.com/file", headers={"Authorization": "Bearer aws_token"}),
    Source("https://other.cdn.com/file", headers={"X-Api-Key": "key123"}),
)

# Комбинация: строки получают глобальные настройки, Source() — свои
komparu.compare_all(
    [
        "https://a.com/f",                                                  # глобальные headers
        "https://b.com/f",                                                  # глобальные headers
        Source("https://special.com/f", headers={"X-Key": "other_key"}),    # свои headers
    ],
    headers={"Authorization": "Bearer token"},
)
```

### Source

```python
@dataclass(frozen=True, slots=True)
class Source:
    url: str
    headers: dict[str, str] | None = None
    timeout: float | None = None
    follow_redirects: bool | None = None
    verify_ssl: bool | None = None
    proxy: str | None = None
```

Поля со значением `None` используют глобальные настройки. Локальные пути тоже можно обернуть в `Source()`, но HTTP-опции для них игнорируются.

## Синхронный API

```python
import komparu
```

### komparu.compare(source_a, source_b, **options) -> bool

Побайтовое сравнение двух источников.

```python
# Локальные файлы
komparu.compare("/path/to/file_a", "/path/to/file_b")

# Удалённые файлы
komparu.compare("https://s3.example.com/a.bin", "https://s3.example.com/b.bin")

# Смешанное
komparu.compare("/local/file", "https://cdn.example.com/file")

# Глобальные HTTP-заголовки (для всех URL-источников)
komparu.compare(
    "/local/file",
    "https://s3.example.com/file",
    headers={"Authorization": "Bearer token123"},
)

# Индивидуальные заголовки для каждого источника
komparu.compare(
    Source("https://s3.aws.com/file", headers={"Authorization": "Bearer aws"}),
    Source("https://gcs.google.com/file", headers={"Authorization": "Bearer gcp"}),
)

# Свой размер чанка
komparu.compare("file_a", "file_b", chunk_size=131072)  # 128 КБ
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `source_a` | `str \| Source` | обязателен | Путь, URL или объект Source |
| `source_b` | `str \| Source` | обязателен | Путь, URL или объект Source |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `headers` | `dict[str, str]` | `None` | Глобальные HTTP-заголовки (для URL без собственной конфигурации) |
| `timeout` | `float` | `30.0` | Глобальный HTTP-таймаут в секундах |
| `size_precheck` | `bool` | `True` | Сравнить размеры перед содержимым |
| `follow_redirects` | `bool` | `True` | Следовать HTTP-редиректам |
| `verify_ssl` | `bool` | `True` | Проверять SSL-сертификаты |
| `quick_check` | `bool` | `True` | Выборочная проверка ключевых смещений перед полным сравнением (только seekable-источники) |
| `proxy` | `str` | `None` | URL прокси (напр. `http://host:port`, `socks5://host:port`) |

**Приоритет:** Параметры функций имеют явные дефолты. `Source().headers` переопределяет параметр `headers`. `configure()` задаёт fallback `headers` и защиту от SSRF (`allow_private_redirects`).

### komparu.compare_dir(dir_a, dir_b, **options) -> DirResult

Рекурсивное сравнение двух директорий.

```python
result = komparu.compare_dir("/dir_a", "/dir_b")

if result.equal:
    print("Директории идентичны")
else:
    print("Только в левой:", result.only_left)
    print("Только в правой:", result.only_right)
    print("Содержимое различается:", result.diff)
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `dir_a` | `str` | обязателен | Первая директория |
| `dir_b` | `str` | обязателен | Вторая директория |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `size_precheck` | `bool` | `True` | Сравнить размеры перед содержимым |
| `quick_check` | `bool` | `True` | Выборочная проверка ключевых смещений перед полным сканированием |
| `follow_symlinks` | `bool` | `True` | Следовать символическим ссылкам |
| `max_workers` | `int` | `0` (авто) | Размер пула потоков (0=авто, 1=последовательно) |

### komparu.compare_archive(archive_a, archive_b, **options) -> DirResult

Сравнение двух архивов как виртуальных директорий.

```python
result = komparu.compare_archive("backup_v1.tar.gz", "backup_v2.zip")
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `path_a` | `str` | обязателен | Первый архив |
| `path_b` | `str` | обязателен | Второй архив |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `max_decompressed_size` | `int` | `1 GB` | Макс. распакованный объём |
| `max_compression_ratio` | `int` | `200` | Макс. степень сжатия |
| `max_archive_entries` | `int` | `100000` | Макс. количество записей |
| `max_entry_name_length` | `int` | `4096` | Макс. длина пути записи |
| `hash_compare` | `bool` | `False` | Хеш-сравнение (потоковый FNV-1a 128-бит). O(entries) по памяти вместо O(total_decompressed). |

### komparu.compare_all(sources, **options) -> bool

Проверка идентичности всех источников.

```python
all_same = komparu.compare_all([
    "/local/copy",
    "https://cdn1.example.com/file",
    "https://cdn2.example.com/file",
])
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `sources` | `list[str \| Source]` | обязателен | Список путей, URL или объектов Source |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `size_precheck` | `bool` | `True` | Сравнить размеры перед содержимым |
| `quick_check` | `bool` | `True` | Выборочная проверка ключевых смещений перед полным сканированием |
| `headers` | `dict[str, str]` | `None` | Глобальные HTTP-заголовки |
| `timeout` | `float` | `30.0` | HTTP-таймаут в секундах |
| `follow_redirects` | `bool` | `True` | Следовать HTTP-редиректам |
| `verify_ssl` | `bool` | `True` | Проверять SSL-сертификаты |
| `max_workers` | `int` | `0` (авто) | Размер пула потоков (0=авто, 1=последовательно). Только sync. |
| `proxy` | `str` | `None` | URL прокси (напр. `http://host:port`, `socks5://host:port`) |

### komparu.compare_many(sources, **options) -> CompareResult

Детальное сравнение множества источников.

```python
result = komparu.compare_many(["file_a", "file_b", "file_c"])

result.all_equal          # bool
result.groups             # list[set[str]] — группы идентичных
result.diff               # dict[tuple[str, str], bool] — попарные результаты
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `sources` | `list[str \| Source]` | обязателен | Список путей, URL или объектов Source |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `size_precheck` | `bool` | `True` | Сравнить размеры перед содержимым |
| `quick_check` | `bool` | `True` | Выборочная проверка ключевых смещений перед полным сканированием |
| `headers` | `dict[str, str]` | `None` | Глобальные HTTP-заголовки |
| `timeout` | `float` | `30.0` | HTTP-таймаут в секундах |
| `follow_redirects` | `bool` | `True` | Следовать HTTP-редиректам |
| `verify_ssl` | `bool` | `True` | Проверять SSL-сертификаты |
| `max_workers` | `int` | `0` (авто) | Размер пула потоков (0=авто, 1=последовательно). Только sync. |
| `proxy` | `str` | `None` | URL прокси (напр. `http://host:port`, `socks5://host:port`) |

### komparu.compare_dir_urls(directory, url_map, **options) -> DirResult

Сравнение локальной директории с маппингом URL.

```python
result = komparu.compare_dir_urls(
    "/local/assets",
    {
        "logo.png": "https://cdn.example.com/logo.png",
        "style.css": "https://cdn.example.com/style.css",
    },
    headers={"Authorization": "Bearer token"},
)
```

**Параметры:**

| Имя | Тип | По умолчанию | Описание |
|-----|-----|--------------|----------|
| `dir_path` | `str` | обязателен | Путь к локальной директории |
| `url_map` | `dict[str, str]` | обязателен | Маппинг relative_path → URL |
| `chunk_size` | `int` | `65536` | Размер чанка в байтах |
| `size_precheck` | `bool` | `True` | Сравнить размеры перед содержимым |
| `quick_check` | `bool` | `True` | Выборочная проверка ключевых смещений перед полным сканированием |
| `headers` | `dict[str, str]` | `None` | Глобальные HTTP-заголовки |
| `timeout` | `float` | `30.0` | HTTP-таймаут в секундах |
| `follow_redirects` | `bool` | `True` | Следовать HTTP-редиректам |
| `verify_ssl` | `bool` | `True` | Проверять SSL-сертификаты |
| `max_workers` | `int` | `0` (авто) | Размер пула потоков (0=авто, 1=последовательно). Только sync. |
| `proxy` | `str` | `None` | URL прокси (напр. `http://host:port`, `socks5://host:port`) |

## Асинхронный API

```python
import komparu.aio
```

Тот же интерфейс, все функции — корутины.

```python
result = await komparu.aio.compare("/path/a", "https://example.com/b")
result = await komparu.aio.compare_dir("/dir_a", "/dir_b")
result = await komparu.aio.compare_archive("a.zip", "b.tar.gz")
result = await komparu.aio.compare_all([...])
result = await komparu.aio.compare_many([...])
result = await komparu.aio.compare_dir_urls("/dir", {...})
```

## Типы результатов

### DirResult

```python
@dataclass(frozen=True, slots=True)
class DirResult:
    equal: bool                     # Все файлы идентичны
    diff: dict[str, DiffReason]     # Файлы с различным содержимым
    only_left: set[str]             # Файлы только в первом источнике
    only_right: set[str]            # Файлы только во втором источнике
```

### CompareResult

```python
@dataclass(frozen=True, slots=True)
class CompareResult:
    all_equal: bool                         # Все источники идентичны
    groups: list[set[str]]                  # Группы идентичных источников
    diff: dict[tuple[str, str], bool]       # Попарные результаты
```

### DiffReason (перечисление)

```python
class DiffReason(str, Enum):
    CONTENT_MISMATCH = "content_mismatch"   # Содержимое различается
    SIZE_MISMATCH = "size_mismatch"         # Размер различается
    MISSING = "missing"                     # Файл отсутствует с одной стороны
    TYPE_MISMATCH = "type_mismatch"         # Файл vs директория
    READ_ERROR = "read_error"               # Не удалось прочитать
```

## Конфигурация

### Глобальные настройки

```python
komparu.configure(
    # I/O
    chunk_size=65536,
    max_workers=0,                         # 0 = авто (min(cpu, 8))
    timeout=30.0,
    follow_redirects=True,
    verify_ssl=True,
    size_precheck=True,
    quick_check=True,

    # HTTP
    headers={},

    # Лимиты безопасности архивов
    max_decompressed_size=1 * 1024**3,    # 1 ГБ на архив
    max_compression_ratio=200,             # abort при превышении
    max_archive_entries=100_000,           # макс. файлов в архиве
    max_entry_name_length=4096,            # макс. длина пути записи

    # Общие лимиты
    comparison_timeout=300.0,              # 5 мин реального времени на вызов

    # Прокси
    proxy=None,                            # None = прямое соединение

    # Защита от SSRF
    allow_private_redirects=False,         # блокировка редиректов на приватные сети
)
```

Все параметры функций имеют явные дефолты. `configure()` задаёт fallback `headers` и `allow_private_redirects` (защита от SSRF). Лимиты безопасности архивов можно менять при каждом вызове.

## Ошибки

```python
class KomparuError(Exception): ...           # Базовая
class SourceNotFoundError(KomparuError): ...  # Файл/URL не найден
class SourceReadError(KomparuError): ...      # Ошибка I/O или HTTP
class ArchiveError(KomparuError): ...         # Не удалось прочитать архив
class ArchiveBombError(ArchiveError): ...     # Декомпрессионная бомба / превышение лимита
class ConfigError(KomparuError): ...          # Невалидная конфигурация
class ComparisonTimeoutError(KomparuError):.. # Превышен таймаут сравнения
```
