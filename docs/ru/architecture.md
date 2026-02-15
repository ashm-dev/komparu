# komparu — Архитектура

## 1. Структура проекта

```
komparu/
├── src/
│   ├── komparu/                  # Python-пакет
│   │   ├── __init__.py           # Публичный синхронный API
│   │   ├── aio.py                # Публичный асинхронный API
│   │   ├── _types.py             # Типы результатов, перечисления
│   │   ├── _config.py            # Конфигурация
│   │   └── py.typed              # PEP 561 маркер
│   └── _core/                    # Исходники C23
│       ├── module.c              # Точка входа CPython-расширения
│       ├── module.h
│       ├── reader.h              # Интерфейс читателя (абстракция)
│       ├── reader_file.c         # Читатель локальных файлов
│       ├── reader_file.h
│       ├── reader_http.c         # HTTP Range читатель (libcurl)
│       ├── reader_http.h
│       ├── reader_archive.c      # Читатель архивов (libarchive)
│       ├── reader_archive.h
│       ├── compare.c             # Движок сравнения
│       ├── compare.h
│       ├── dirwalk.c             # Обход директорий
│       ├── dirwalk.h
│       ├── pool.c                # Пул потоков
│       ├── pool.h
│       ├── async_task.c          # Жизненный цикл async-задач (CAS, eventfd/pipe)
│       ├── async_task.h
│       ├── async_curl.c          # Строительные блоки libcurl multi
│       ├── async_curl.h
│       └── compat.h              # Макросы совместимости Python/платформ
├── tests/
│   ├── conftest.py
│   ├── test_compare_local.py
│   ├── test_compare_http.py
│   ├── test_compare_dir.py
│   ├── test_compare_archive.py
│   ├── test_parallel.py
│   ├── test_async.py
│   └── test_config.py
├── benchmarks/
├── docs/
│   ├── en/
│   └── ru/
├── CMakeLists.txt                # Система сборки
├── pyproject.toml
├── LICENSE
├── README.md
└── .github/
    └── workflows/
```

## 2. C23 ядро — диаграмма модулей

```
┌──────────────────────────────────────────────────┐
│                   module.c                        │
│         Точка входа CPython-расширения            │
│      Управление GIL, free-threading              │
└──────┬───────────┬──────────────┬────────────────┘
       │           │              │
       v           v              v
┌──────────┐ ┌──────────┐ ┌──────────────┐
│compare.c │ │dirwalk.c │ │   pool.c     │
│  движок  │ │  обход   │ │ пул потоков  │
│сравнения │ │директорий│ │очередь задач │
└──────┬───┘ └──────────┘ └──────────────┘
       │
       v
┌──────────────── reader.h (интерфейс) ────────────┐
│                                                   │
│  ┌───────────────┐ ┌──────────────┐ ┌───────────┐│
│  │reader_file.c  │ │reader_http.c │ │reader_    ││
│  │mmap / read()  │ │libcurl       │ │archive.c  ││
│  │               │ │Range-запросы │ │libarchive ││
│  └───────────────┘ └──────────────┘ └───────────┘│
└──────────────────────────────────────────────────┘
```

## 3. Интерфейс Reader

Абстрактный читатель — единый API для всех типов источников.

```c
typedef struct komparu_reader {
    // Прочитать до `size` байт в `buf`. Вернуть количество, 0 = EOF, -1 = ошибка.
    int64_t (*read)(struct komparu_reader *self, void *buf, size_t size);

    // Получить полный размер если известен. Вернуть -1 если неизвестен.
    int64_t (*get_size)(struct komparu_reader *self);

    // Закрыть и освободить ресурсы.
    void (*close)(struct komparu_reader *self);

    // Непрозрачное состояние.
    void *ctx;
} komparu_reader_t;
```

### Реализации

| Reader | Backend | Стратегия чтения |
|--------|---------|------------------|
| `reader_file` | `mmap` (Linux/macOS), `ReadFile` (Windows) | Страницы через mmap, кэширование на уровне ОС |
| `reader_http` | libcurl | HTTP Range-запросы, переиспользование соединений |
| `reader_archive` | libarchive | Последовательное потоковое чтение |

## 4. Алгоритм сравнения

```
compare(reader_a, reader_b, chunk_size):
    1. size_a = reader_a.get_size()
       size_b = reader_b.get_size()
    2. if оба известны AND size_a != size_b → return false
    3. цикл:
         n_a = reader_a.read(buf_a, chunk_size)
         n_b = reader_b.read(buf_b, chunk_size)
         if n_a != n_b → return false
         if n_a == 0   → return true   // оба EOF
         if memcmp(buf_a, buf_b, n_a) != 0 → return false
    4. недостижимо
```

Ключевые свойства:
- Память: 2 * chunk_size (два буфера)
- I/O: останавливается при первом различии
- Сеть: получает только нужные чанки через Range

## 5. Сравнение директорий

```
compare_dir(dir_a, dir_b):
    1. files_a = dirwalk(dir_a)  → множество относительных путей
       files_b = dirwalk(dir_b)  → множество относительных путей
    2. only_left  = files_a - files_b
       only_right = files_b - files_a
       common     = files_a & files_b
    3. parallel_for file in common:
         if not compare(dir_a/file, dir_b/file):
             diff[file] = CONTENT_MISMATCH
    4. return DirResult(equal, diff, only_left, only_right)
```

## 6. Пул потоков

```c
typedef struct komparu_pool {
    pthread_t *threads;
    size_t num_workers;
    pool_task_t *queue;       // Динамический массив (FIFO, head/tail)
    size_t queue_cap;
    size_t queue_head;
    size_t queue_tail;
    size_t queue_count;
    pthread_mutex_t mutex;
    pthread_cond_t task_avail;
    pthread_cond_t all_done;
    size_t active_count;
    bool shutdown;
} komparu_pool_t;
```

- Очередь задач: динамический массив с FIFO-семантикой (head/tail), защищённый mutex + condvar
- Воркеры по умолчанию: `min(sysconf(_SC_NPROCESSORS_ONLN), 8)`
- GIL освобождается перед отправкой работы в пул
- Одна задача: сравнение одной пары файлов
- `all_done` condvar для ожидания завершения всех задач
- Массив автоматически расширяется при заполнении

## 7. Варианты сборки Python

### compat.h — условная компиляция

```c
// Определение версии Python
#if PY_VERSION_HEX >= 0x030E0000    // 3.14+
    #define KOMPARU_PY314 1
#elif PY_VERSION_HEX >= 0x030D0000  // 3.13+
    #define KOMPARU_PY313 1
#endif

// Определение free-threaded сборки
#ifdef Py_GIL_DISABLED
    #define KOMPARU_FREE_THREADED 1
#endif

// Управление GIL
#ifdef KOMPARU_FREE_THREADED
    // GIL не существует — операции не нужны
    #define KOMPARU_GIL_RELEASE()
    #define KOMPARU_GIL_ACQUIRE()
#else
    #define KOMPARU_GIL_RELEASE() Py_BEGIN_ALLOW_THREADS
    #define KOMPARU_GIL_ACQUIRE() Py_END_ALLOW_THREADS
#endif
```

### Инициализация модуля

```c
static struct PyModuleDef_Slot module_slots[] = {
#ifdef KOMPARU_FREE_THREADED
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL}
};
```

## 8. Архитектура Sync vs Async

### Sync (komparu/__init__.py → C-расширение)

```
Вызов Python → C-расширение → освобождение GIL → C I/O + сравнение → захват GIL → возврат
```

Полный конвейер в C. Максимальная производительность. Один переход через FFI.

### Async (komparu/aio.py → C pool + eventfd/pipe + asyncio)

```
Python → async_compare_start() → C pool ставит задачу → worker (без GIL):
    open_reader (file/HTTP) → komparu_compare → write в eventfd/pipe
Python: asyncio.loop.add_reader(fd) → callback → async_compare_result(task)
```

- ВСЕ async-функции (`compare`, `compare_dir`, `compare_archive`, `compare_dir_urls`) используют одну схему: C pool + eventfd/pipe + `asyncio.loop.add_reader()`
- Worker-потоки используют libcurl easy (блокирующий) — тот же I/O что и sync-путь
- Нет `curl_multi_socket_action` интеграции (`async_curl.c` существует как строительные блоки для будущего неблокирующего HTTP, но не используется основным async API)
- Нет `io_uring` или `kqueue` для файлового async I/O — workers используют mmap как и sync
- Нет Python awaitable-протокола (`__await__`) — обычные `async def` + `add_reader`
- CAS-based жизненный цикл задач: `RUNNING → DONE` или `RUNNING → ORPHANED`
- Весь I/O в C — без Python HTTP-библиотек (без aiohttp, без aiofiles)
- Event loop не блокируется: вычисления и I/O в worker-потоках пула, Python только получает оповещение через fd

Почему раздельно: sync выполняет всё в вызывающем потоке (GIL released).
Async отправляет задачу в C pool и возвращает управление event loop.
Одно C-ядро, один и тот же I/O (libcurl easy, mmap). Разница — кто вызывает и как ждут результат.

## 9. Внешние зависимости

| Библиотека | Назначение | Линковка |
|------------|-----------|----------|
| libcurl | HTTP/HTTPS — easy интерфейс (sync и async worker-потоки) | Динамическая (системная) или статическая (vendored для wheels). Требуется c-ares или threaded resolver. |
| libarchive | Чтение архивов (zip, tar, 7z и т.д.) | Динамическая (системная) или статическая (vendored для wheels) |
| pthreads | Пул потоков (Linux/macOS) | Системная |

Без Python HTTP/IO зависимостей. Весь I/O в C через libcurl easy и mmap. Async через C pool + eventfd/pipe.

## 10. Матрица платформ

| Возможность | Linux | macOS | Windows |
|-------------|-------|-------|---------|
| File reader | mmap | mmap | ReadFile + CreateFileMapping |
| HTTP reader | libcurl | libcurl | libcurl |
| Archive reader | libarchive | libarchive | libarchive |
| Thread pool | pthreads | pthreads | Windows threads |
| Free-threading | Да (3.13t+) | Да (3.13t+) | Да (3.13t+) |
