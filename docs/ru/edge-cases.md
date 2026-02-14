# komparu — Полный реестр крайних случаев

Анализ в три прохода. Статусы:
- **HANDLE** — обработать в коде
- **DETECT** — обнаружить и сообщить (ошибка/предупреждение)
- **DOCUMENT** — ожидаемое поведение, задокументировать

---

## I. Источники / Ввод

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 1 | Оба файла 0 байт | DOCUMENT | `True`. Пустое равно пустому. `min_size` — opt-in для строгих проверок. |
| 2 | Один файл 0 байт, другой нет | HANDLE | Size pre-check → мгновенный `False`. |
| 3 | Один и тот же путь (`compare("/a", "/a")`) | HANDLE | Определяем через `(dev, ino)` → мгновенный `True`, без I/O. |
| 4 | Одинаковый URL | DOCUMENT | **Без шортката.** Один URL может вернуть разный контент (динамика, CDN-ноды, кэш). Всегда сравниваем. Только локальные файлы получают шорткат через inode. |
| 4a | URL с разными query-параметрами | DOCUMENT | Разные ресурсы. `?v=1` ≠ `?v=2`. Query-параметры не нормализуем. |
| 5 | Источник не существует (локальный) | HANDLE | `SourceNotFoundError` с путём. |
| 6 | Источник — директория, не файл | HANDLE | `SourceReadError("'/path' is a directory, not a file")`. |
| 7 | Источник — симлинк | HANDLE | Следуем по умолчанию (читаем цель). `follow_symlinks` для директорий. |
| 8 | Источник — спецфайл (device, pipe, socket, FIFO) | HANDLE | `SourceReadError("'/dev/sda' is not a regular file")`. Отклоняем. |
| 9 | Источник — `/dev/null` | HANDLE | Как 0-байтовый файл. Кейс #1. |
| 10 | Источник — `/dev/zero` или `/dev/urandom` | HANDLE | Отклонён кейсом #8 (не обычный файл). |
| 11 | Путь с пробелами, юникодом | HANDLE | Передаём как есть в ОС. Работает на всех платформах. |
| 12 | Путь превышает PATH_MAX | HANDLE | ОС возвращает ошибку → `SourceNotFoundError`. |
| 13 | Очень большой файл (>4 ГБ) | HANDLE | 64-битные смещения (`int64_t`), `mmap` с `MAP_NORESERVE`. |
| 14 | Очень большой файл (>2 ТБ) | HANDLE | То же. `off_t` 64-битный на 64-битных системах. Чанковый, без полного маппинга. |
| 15 | Относительный путь | HANDLE | Разрешаем в абсолютный через `realpath()` до сравнения. |
| 16 | Слеш в конце пути | HANDLE | Нормализуем: убираем trailing slashes для файлов. |
| 17 | Файл на NFS/SMB | DOCUMENT | Работает. Производительность зависит от сети. `mmap` может вести себя иначе. |
| 18 | Файл на read-only ФС | DOCUMENT | Мы только читаем — OK. |
| 19 | Hard links (один inode, разные пути) | HANDLE | Определяем кейсом #3 (`dev, ino` совпадают) → мгновенный `True`. |
| 20 | `str` vs `bytes` путь в Python | HANDLE | Принимаем оба. `str` кодируем через `os.fsencode()`. |
| 21 | Путь с null-байтом | HANDLE | Отклоняем: `ConfigError("path contains null byte")`. |

## II. HTTP / Сеть

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 22 | HTTP 200 вместо 206 (нет поддержки Range) | HANDLE | Определяем при первом запросе. Откат на последовательный стриминг. `quick_check` отключается для этого источника. |
| 23 | HTTP 301/302 редирект | HANDLE | Следуем по умолчанию. `follow_redirects=False` для отключения. |
| 24 | Цепочка редиректов (A→B→C→D) | HANDLE | libcurl `MAXREDIRS=10`. Превышение → `SourceReadError`. |
| 25 | Цикл редиректов (A→B→A) | HANDLE | libcurl определяет → `SourceReadError("redirect loop")`. |
| 25a | **SSRF через редирект** | HANDLE | Атакер редиректит на `http://localhost/admin`. Блокируем редиректы на приватные сети: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `::1`, `localhost`. `CURLOPT_REDIR_PROTOCOLS` = только HTTP/HTTPS. Настраиваемый whitelist/blacklist. |
| 26 | HTTP 403 Forbidden | HANDLE | `SourceReadError("HTTP 403 for 'url'")`. |
| 27 | HTTP 404 Not Found | HANDLE | `SourceNotFoundError("HTTP 404 for 'url'")`. |
| 28 | HTTP 429 Too Many Requests | HANDLE | `SourceReadError` со статус-кодом. **Без авто-ретрая** — rate limits сервера, ретраи только ухудшат. Ретраи — opt-in. |
| 29 | HTTP 5xx ошибки сервера | HANDLE | `SourceReadError` со статус-кодом. Ретрай только при `retries > 0` (по умолчанию: `0`, отключено). |
| 30 | Таймаут соединения | HANDLE | `SourceReadError`. Ретрай только при `retries > 0`. |
| 31 | Обрыв соединения в процессе | HANDLE | `SourceReadError`. Ретрай только при `retries > 0`. Возможно возобновление с позиции если сервер поддерживает Range. |
| 32 | Ошибка DNS | HANDLE | `SourceReadError("DNS resolution failed for 'host'")`. |
| 33 | Невалидный/просроченный SSL-сертификат | HANDLE | Ошибка по умолчанию. `verify_ssl=False` для отключения. |
| 34 | Self-signed сертификат | HANDLE | Аналогично #33. |
| 35 | `Content-Encoding: gzip` в ответе на Range | HANDLE | Отправляем `Accept-Encoding: identity`. Если сервер игнорирует: декомпрессия через libcurl. |
| 36 | `Transfer-Encoding: chunked` | HANDLE | libcurl обрабатывает прозрачно. |
| 37 | `Content-Length` врёт | HANDLE | Size pre-check — рекомендация. Чанковое сравнение ловит реальный EOF. |
| 38 | Нет `Content-Length` заголовка | HANDLE | Пропускаем size pre-check для этого источника. Чанковое сравнение работает без него. |
| 39 | Сервер возвращает неправильные байты для Range | HANDLE | Проверяем `Content-Range` в ответе. Несовпадение → `SourceReadError`. |
| 40 | Presigned URL истекает в процессе | DETECT | HTTP 403 в середине → `SourceReadError` с контекстом. Документируем: используйте достаточный TTL. |
| 41 | Очень медленный сервер (1 байт/сек) | HANDLE | `timeout` для per-request. `comparison_timeout` для общего wall-clock. |
| 42 | Сервер зависает (нет ответа) | HANDLE | `timeout` → `SourceReadError`. |
| 43 | Сервер закрывает соединение после N запросов | HANDLE | libcurl переподключается автоматически. Connection pooling. |
| 44 | CDN отдаёт разный контент с разных нод | DOCUMENT | Не определяемо на нашем уровне. Ответственность пользователя. |
| 45 | Контент зависит от User-Agent или Referer | DOCUMENT | Пользователь задаёт `headers` при необходимости. |
| 46 | URL с query-параметрами | HANDLE | Передаём как есть. `?v=2` — другой URL. |
| 47 | URL с фрагментом (#) | HANDLE | Убираем фрагмент перед запросом (фрагменты — клиентская часть). |
| 48 | URL с `user:pass@host` | HANDLE | libcurl поддерживает. |
| 49 | Проблемы URL-кодирования (%20 vs пробел) | HANDLE | Нормализуем URL. Не кодируем повторно. |
| 50 | IPv6 URL (`http://[::1]/file`) | HANDLE | libcurl поддерживает. |
| 51 | Нестандартные порты | HANDLE | libcurl поддерживает. |
| 52 | Требуется HTTP proxy | HANDLE | Уважаем `HTTP_PROXY`/`HTTPS_PROXY` env vars. libcurl делает это по умолчанию. |
| 52a | **Синхронный DNS блокирует пул потоков** | HANDLE | Стандартный libcurl использует блокирующий DNS. В пуле потоков блокирует воркеры. Требовать libcurl с c-ares или threaded resolver. |
| 53 | HTTPS с клиентским сертификатом | DOCUMENT | Не поддерживается в v1. |
| 54 | Punycode / интернационализированные домены | HANDLE | libcurl обрабатывает IDN-конвертацию. |
| 55 | `file://` URL | HANDLE | Трактуем как локальный путь. Используем file reader. |
| 56 | `ftp://`, `data:`, `ws://` URL | HANDLE | `ConfigError("unsupported URL scheme")`. Только `http`, `https`, `file`. |
| 57 | HTTP/2 vs HTTP/1.1 | HANDLE | libcurl выбирает автоматически. |
| 58 | Сервер возвращает 0 байт с 200 OK | DOCUMENT | Как пустой файл. Кейс #1. `min_size` для защиты. |
| 59 | ETag изменился между Range-запросами | HANDLE | Сохраняем ETag от первого запроса. Проверяем в последующих. Несовпадение → `SourceReadError("source content changed during comparison")`. |
| 60a | Сервер отдаёт только целиком (нет Range, нет HEAD) | HANDLE | Определяем при первом запросе (200 вместо 206). Переключаемся на полный последовательный стриминг. `quick_check` отключается. |
| 60b | Сервер rate-limitit Range-запросы | DOCUMENT | Несколько Range-запросов на файл могут вызвать rate limit. С `quick_check` — до 4 запросов. Отключить: `quick_check=False` → один последовательный запрос. |
| 60c | Ретрай ухудшает rate limit | DOCUMENT | `retries=0` (по умолчанию). Ретраи — opt-in. Пользователь включает только если уверен что сервер выдержит. |

## III. Локальная ФС

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 61 | Файл изменён во время сравнения | HANDLE | `integrity_check=True` (default): фиксируем `mtime`+`size` до, проверяем после. Изменился → `SourceReadError`. |
| 62 | Файл удалён во время сравнения | HANDLE | ОС возвращает ошибку → `SourceReadError`. |
| 63 | Файл заменён во время сравнения | HANDLE | `integrity_check` ловит через изменение inode или mtime. |
| 64 | Файл обрезан во время сравнения | HANDLE | Read возвращает меньше байт → ловится чанковым сравнением или `integrity_check`. |
| 65 | Файл дозаписан во время сравнения | HANDLE | `integrity_check` ловит через size/mtime. |
| 66 | Sparse-файлы | DOCUMENT | `mmap` читает дыры как нули. Два sparse-файла с одинаковым логическим содержимым = equal. Корректно. |
| 67 | Extended attributes (xattr) | DOCUMENT | Игнорируем. Сравниваем только содержимое. |
| 68 | ACL | DOCUMENT | Игнорируем. ACL влияют на доступ, не на содержимое. |
| 69 | Разные permissions, одинаковый контент | DOCUMENT | `True`. Сравниваем содержимое, не метаданные. |
| 70 | Разные timestamps, одинаковый контент | DOCUMENT | `True`. Содержимое, не метаданные. |
| 71 | Достигнут лимит файловых дескрипторов | HANDLE | `open()` → `EMFILE` → `SourceReadError("too many open files")`. |
| 72 | Ошибка I/O диска (bad sector) | HANDLE | ОС → `EIO` → `SourceReadError`. |
| 73 | Файл заблокирован другим процессом | HANDLE | Linux/macOS: advisory locks не мешают чтению. Windows: mandatory locks → `SourceReadError`. |
| 74 | `mmap` падает (нехватка адресного пространства) | HANDLE | Откат на буферизованный `read()`. Логируем предупреждение. |
| 74a | **SIGBUS при mmap после обрезания файла** | HANDLE | Если файл обрезан другим процессом во время mmap — доступ за границей нового размера вызывает SIGBUS, крашит Python. Нужен `sigaction` обработчик с `sigsetjmp`/`siglongjmp` в C для перехвата и конвертации в `SourceReadError`. Критично для безопасности библиотеки. |
| 75 | Файл на FUSE | DOCUMENT | Работает если FUSE реализует стандартный POSIX read. |
| 76 | Файл в /proc, /sys | HANDLE | Отклоняем если не обычный файл (#8). |

## IV. Сравнение директорий

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 77 | Обе директории пустые | HANDLE | `DirResult(equal=True, ...)`. |
| 78 | Одна пустая, другая нет | HANDLE | Все файлы в `only_left`/`only_right`. `equal=False`. |
| 79 | Директория не существует | HANDLE | `SourceNotFoundError`. |
| 80 | Путь — файл, не директория | HANDLE | `SourceReadError("is a file, not a directory")`. |
| 81 | Скрытые файлы (dotfiles) | HANDLE | Включены по умолчанию. `exclude_hidden=True` для пропуска. |
| 82 | Глубоко вложенная структура (>100 уровней) | HANDLE | Итеративный обход (не рекурсивный в стеке). Без stack overflow. |
| 83 | Директория с 1M+ файлов | HANDLE | Потоковый обход в C. Память = O(глубина дерева). |
| 84 | Цикл симлинков | HANDLE | Трекинг `(dev, ino)`. Пропуск посещённых. Предупреждение в результате. |
| 85 | Dangling симлинк | HANDLE | `on_error="report"`: `DiffReason.READ_ERROR`. `on_error="raise"`: `SourceReadError`. |
| 86 | Нет доступа к поддиректории | HANDLE | Аналогично #85. |
| 87 | Нет доступа к файлу | HANDLE | Аналогично #85. |
| 88 | Нет доступа к директории вообще | HANDLE | `SourceReadError("permission denied")`. |
| 89 | Unicode-нормализация имён (NFC vs NFD) | HANDLE | `normalize_unicode=True` (default): NFC для сопоставления. |
| 90 | Чувствительность к регистру (macOS/Windows vs Linux) | HANDLE | `case_sensitive=None` (default): автоопределение от ФС. |
| 91 | `.DS_Store` / `Thumbs.db` | DOCUMENT | Включены по умолчанию. Исключить через `exclude_patterns`. |
| 92 | Mount points внутри директории | DOCUMENT | Обходятся по умолчанию. |
| 93 | Запись — файл в dir_a, директория в dir_b | HANDLE | `DiffReason.TYPE_MISMATCH`. |
| 94 | Слеш в конце пути директории | HANDLE | Нормализуем. |
| 95 | Обе директории — один путь | HANDLE | Определяем через `(dev, ino)` → мгновенный `DirResult(equal=True)`. |

## V. Сравнение архивов

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 96 | Пустой архив | HANDLE | Оба пустые → `equal=True`. Один пустой → `only_left`/`only_right`. |
| 97 | Архив с только directory entries | HANDLE | Пропускаем. Сравниваем только файлы. |
| 98 | Zip-бомба (классическая) | HANDLE | `max_decompressed_size`, `max_compression_ratio`. См. `security.md`. |
| 99 | Рекурсивная бомба | HANDLE | Никогда не распаковываем рекурсивно. Вложенный архив = бинарный blob. Жёсткое правило. |
| 100 | Quine-бомба | HANDLE | Аналогично #99. |
| 101 | Path traversal в архиве (`../`) | HANDLE | Санитизация путей всегда включена. Отклоняем `..`. |
| 102 | Дублированные имена записей | HANDLE | Последняя запись побеждает. Документируем. |
| 103 | Записи в разном порядке | HANDLE | Сортировка по пути перед сопоставлением. Порядок не важен. |
| 104 | Очень длинное имя записи | HANDLE | `max_entry_name_length`. |
| 105 | Null-байты в имени записи | HANDLE | Отклоняем: санитизация путей. |
| 106 | Симлинки внутри архива | HANDLE | Пропускаем. Сравниваем только обычные файлы. |
| 107 | Hard links внутри архива | HANDLE | Разрешаем к целевому содержимому. |
| 108 | Спецфайлы (devices) внутри архива | HANDLE | Пропускаем. |
| 109 | Повреждённый / обрезанный архив | HANDLE | libarchive → `ArchiveError`. |
| 110 | Архив с паролем | HANDLE | `ArchiveError("archive is password-protected")`. Не поддерживается в v1. |
| 111 | Разные форматы архивов, одинаковый контент | HANDLE | Работает. Сравниваем по содержимому записей, не по формату. |
| 112 | Split / multi-volume архив | HANDLE | `ArchiveError("multi-volume archives not supported")`. |
| 113 | Self-extracting архив (SFX) | HANDLE | Если libarchive распознаёт: работает. Если нет: `ArchiveError`. |
| 114 | Удалённый архив (URL) | HANDLE | HTTP reader подаёт в libarchive. Последовательный стриминг. `quick_check` отключён. |
| 115 | Записи в разных кодировках (CP866, Shift-JIS) | HANDLE | libarchive обрабатывает. Откат на raw bytes для сопоставления. |
| 116 | Tar GNU vs POSIX (pax) | HANDLE | libarchive абстрагирует. Одинаковый контент = одинаковый результат. |
| 117 | Zip64 (записи > 4 ГБ) | HANDLE | libarchive поддерживает Zip64. |
| 118 | Запись — архивный формат (без рекурсивной распаковки) | HANDLE | Сравнивается как бинарный blob. Кейс #99. |
| 119 | Архив с комментариями | DOCUMENT | Комментарии игнорируются. Сравниваем содержимое записей. |

## VI. Логика сравнения

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 120 | Идентичный контент | HANDLE | Полное сравнение → `True`. |
| 121 | Различие в байте 0 | HANDLE | Первый чанк → мгновенный `False`. |
| 122 | Различие в последнем байте | HANDLE | `quick_check` ловит через sample последнего чанка. Без него: полное чтение. |
| 123 | Одинаковый контент + trailing null bytes | HANDLE | Разный размер → `False`. Одинаковый размер но разный контент → `False`. |
| 124 | Очень маленький файл (1 байт) | HANDLE | Один чанк, одно сравнение. |
| 125 | Файл ровно `chunk_size` байт | HANDLE | Один полный чанк + один пустой read (EOF). |
| 126 | `chunk_size + 1` байт | HANDLE | Два чанка. |
| 127 | `chunk_size - 1` байт | HANDLE | Один неполный чанк. |
| 128 | `chunk_size` > размер файла | HANDLE | Один неполный чанк. |
| 129 | `quick_check` на non-seekable источнике | HANDLE | Авто-отключение `quick_check`. Откат на sequential. |
| 130 | `quick_check` совпал, но полное сравнение нашло различие | HANDLE | Корректно по дизайну. Sample совпадение ≠ полное совпадение. Полное сравнение всегда следует. |
| 131 | `compare_all([])` — пустой список | HANDLE | `ConfigError("at least 2 sources required")`. |
| 132 | `compare_all([один])` — один источник | HANDLE | `ConfigError("at least 2 sources required")`. |
| 133 | `compare_many` со 100+ источниками | HANDLE | O(n) сравнений с первым как эталон. Не O(n²). |
| 134 | `compare_dir_urls` с пустым маппингом | HANDLE | Все локальные файлы в `only_left`. |
| 135 | `compare_dir_urls` с URL что отдаёт 404 | HANDLE | `on_error="report"` → `DiffReason.READ_ERROR`. `on_error="raise"` → `SourceNotFoundError`. |

## VII. Многопоточность

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 136 | `max_workers=0` | HANDLE | `ConfigError("max_workers must be >= 1")`. |
| 137 | `max_workers=1` | HANDLE | Последовательное выполнение. Валидно. |
| 138 | `max_workers` > CPU count | HANDLE | Разрешено. Документируем что oversubscription может снизить производительность. |
| 139 | `max_workers` > количество пар файлов | HANDLE | Лишние воркеры простаивают. Безвредно. |
| 140 | Два параллельных сравнения одного источника | HANDLE | Каждый открывает свой FD / HTTP connection. Нет разделяемого состояния. |
| 141 | Исчерпание файловых дескрипторов | HANDLE | Каждый воркер ≤2 FD. Макс: `max_workers * 2`. По умолчанию 16. |
| 142 | Сигнал (SIGINT/SIGTERM) | HANDLE | C-код проверяет `PyErr_CheckSignals()` между чанками. Чистое завершение. |
| 143 | `KeyboardInterrupt` | HANDLE | GIL acquire → `PyErr_CheckSignals()` → `KeyboardInterrupt` пробрасывается. Пул чистится. |
| 144 | Исключение в одном воркере | HANDLE | Собираем исключение. Отменяем остальные задачи. Возвращаем первую ошибку. |
| 145 | Thread safety libcurl handles | HANDLE | Каждый поток — свой `CURL*`. Без sharing. |
| 146 | Thread safety libarchive | HANDLE | Каждый поток — свой `archive*`. Без sharing. |
| 147 | Free-threaded Python: race conditions | HANDLE | Нет разделяемого мутабельного состояния в C. Атомарные операции для счётчиков. |
| 148 | Завершение пула пока задачи выполняются | HANDLE | Флаг `shutdown`. Воркеры завершают текущий чанк, затем выходят. |
| 149 | Нагрузка на память при высоком параллелизме | DOCUMENT | Макс: `max_workers * 2 * chunk_size`. По умолчанию: 1 МБ. |

## VIII. Конфигурация / Валидация

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 150 | `chunk_size=0` | HANDLE | `ConfigError("chunk_size must be > 0")`. |
| 151 | `chunk_size=-1` | HANDLE | `ConfigError("chunk_size must be > 0")`. |
| 152 | `chunk_size` не степень 2 | DOCUMENT | Разрешено. Степени 2 оптимальны но не обязательны. |
| 153 | Очень большой `chunk_size` (1 ГБ) | DOCUMENT | Разрешено. Память = `2 * chunk_size * max_workers`. Выбор пользователя. |
| 154 | `timeout=0` | HANDLE | `ConfigError("timeout must be > 0 or None")`. |
| 155 | `timeout < 0` | HANDLE | Аналогично #154. |
| 156 | `comparison_timeout=0` | HANDLE | `ConfigError`. |
| 157 | `retries < 0` | HANDLE | `ConfigError("retries must be >= 0")`. |
| 158 | `retries=0` | HANDLE | Без ретраев. Первая ошибка — финальная. Валидно. |
| 159 | `Source()` с локальным путём | HANDLE | HTTP-опции игнорируются. File reader. Без ошибки. |
| 160 | `Source()` с пустыми headers `{}` | HANDLE | Как отсутствие кастомных headers. Глобальные настройки. |
| 161 | `Source()` с пустым URL `""` | HANDLE | `ConfigError("empty source path")`. |
| 162 | `configure()` из нескольких потоков | HANDLE | Глобальный конфиг защищён мьютексом. Последняя запись побеждает. |
| 163 | Per-call опции vs глобальный конфиг | DOCUMENT | Per-call побеждает. Приоритет: `Source()` > вызов > `configure()`. |
| 164 | Все лимиты архивов = `None` | DOCUMENT | Без лимитов. Валидно. Ответственность пользователя. |
| 165 | Все лимиты архивов = `0` | HANDLE | `ConfigError("limit must be > 0 or None")`. |

## IX. Платформы

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 166 | Windows: путь > 260 символов | HANDLE | Используем `\\?\` префикс для длинных путей. |
| 167 | Windows: зарезервированные имена (CON, PRN, NUL) | HANDLE | ОС → ошибка → `SourceReadError`. |
| 168 | Windows: mandatory file locking | HANDLE | Не можем прочитать → `SourceReadError("file is locked")`. |
| 169 | Windows: backslash vs forward slash | HANDLE | Нормализуем к системному разделителю. Принимаем оба. |
| 170 | Windows: регистр буквы диска (`C:` vs `c:`) | HANDLE | Нормализуем к верхнему для same-source detection. |
| 171 | macOS: case-insensitive FS (APFS default) | HANDLE | `case_sensitive` автоопределение от ФС. |
| 172 | macOS: resource forks (`._` файлы) | DOCUMENT | Включены по умолчанию. Исключить через `exclude_patterns`. |
| 173 | macOS: `.DS_Store` | DOCUMENT | Аналогично #172. |
| 174 | Linux: файлы в `/proc`, `/sys` | HANDLE | Отклоняем если не обычный файл (#8). |
| 175 | Linux: SELinux/AppArmor запрещает доступ | HANDLE | ОС → `EACCES` → `SourceReadError`. |
| 176 | Docker: overlay filesystem | DOCUMENT | Работает. Overlay — POSIX-совместим. |
| 177 | Кроссплатформенные line endings (CRLF vs LF) | DOCUMENT | Побайтовое сравнение. `\r\n` ≠ `\n`. Корректно — сравниваем содержимое, не текст. |

## X. Интеграция с Python

| # | Кейс | Статус | Поведение |
|---|------|--------|-----------|
| 178 | Вызов из нескольких Python-потоков | HANDLE | GIL освобождается в C. Thread-safe по дизайну. |
| 179 | Sync API в async-контексте | DOCUMENT | Работает, но блокирует event loop. Документируем: используйте `komparu.aio`. |
| 180 | Async API без event loop | HANDLE | Python → `RuntimeError`. Стандартное поведение asyncio. |
| 181 | Утечка памяти в C-расширении | HANDLE | Valgrind / ASan тесты в CI. Корректная очистка во всех путях ошибок. |
| 182 | GC во время сравнения | HANDLE | C корректно держит ссылки на Python-объекты. Без dangling pointers. |
| 183 | Безопасность субинтерпретаторов (3.12+) | HANDLE | Multi-phase init (`Py_mod_create`). Per-interpreter state, без глобалов. |
| 184 | `pickle` / `copy` объектов результата | HANDLE | `DirResult`, `CompareResult` — frozen dataclasses. Picklable по умолчанию. |
| 185 | Различия C API Python 3.12 vs 3.13 vs 3.14 | HANDLE | `compat.h` с условными макросами. CI тестирует все версии. |
| 186 | Совместимость с PyPy | DOCUMENT | Не поддерживается в v1. C-расширение использует CPython-specific API. |
