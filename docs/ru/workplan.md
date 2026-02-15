# komparu — План работы

## Фаза 1: Фундамент

**Цель:** Сравнение локальных файлов работает end-to-end.

- [x] Структура проекта: `CMakeLists.txt`, `pyproject.toml`
- [x] C23 ядро: интерфейс `reader.h`, `reader_file.c` (mmap)
- [x] C23 ядро: `compare.c` — движок чанкового сравнения
- [x] C23 ядро: `module.c` — CPython-расширение, управление GIL
- [x] Python sync API: `komparu.compare()` для локальных файлов
- [x] `compat.h` — макросы версий/платформ
- [x] Тесты: сравнение локальных файлов (одинаковые, разные, пустые, большие)
- [x] CI: GitHub Actions, Python 3.12 на Linux

**Результат:** `komparu.compare("/a", "/b")` работает.

## Фаза 2: HTTP-поддержка

**Цель:** Сравнение удалённых URL через Range-запросы.

- [x] C23 ядро: `reader_http.c` — libcurl, Range-запросы, переиспользование соединений
- [x] HTTP-опции: заголовки, таймаут, редиректы, SSL
- [x] Смешанное сравнение: локальный + удалённый
- [x] Предварительная проверка размера через HEAD / Content-Length
- [x] Тесты: mock HTTP-сервер (pytest-httpserver), проверка Range
- [x] Тест ранней остановки: большой удалённый файл, различие в первом чанке

**Результат:** `komparu.compare("/local", "https://remote")` работает.

## Фаза 3: Директории и архивы

**Цель:** Рекурсивное сравнение директорий и архивов.

- [x] C23 ядро: `dirwalk.c` — рекурсивный обход, относительные пути
- [x] Python: `compare_dir()` — сравнение директорий
- [x] C23 ядро: `reader_archive.c` — потоковое чтение через libarchive
- [x] Python: `compare_archive()` — сравнение архивов
- [x] Python: `compare_dir_urls()` — директория vs маппинг URL
- [x] Типы результатов: `DirResult`, `DiffReason`
- [x] Тесты: директории (вложенные, симлинки, пустые), архивы (zip, tar.gz, смешанные)

**Результат:** `komparu.compare_dir()`, `compare_archive()`, `compare_dir_urls()` работают.

## Фаза 4: Множественное сравнение и параллелизм

**Цель:** Пакетное сравнение с пулом потоков.

- [x] C23 ядро: `pool.c` — пул потоков, очередь задач
- [x] Python: `compare_all()`, `compare_many()`, `CompareResult`
- [x] Параллельное сравнение директорий (пары файлов сравниваются конкурентно)
- [x] Настраиваемый `max_workers`
- [x] Тесты: корректность параллелизма, лимиты ресурсов
- [x] Бенчмарки: параллельно vs последовательно

**Результат:** Мульти-файловое и мульти-директорийное сравнение с параллелизмом.

## Фаза 5: Async API

**Цель:** Нативный async API без обёртки над sync.

- [x] `komparu/aio.py` — async-версии всех публичных функций
- [x] Инфраструктура C pool: `async_task.c` — жизненный цикл задач через CAS, оповещение через eventfd/pipe
- [x] Async compare и compare_dir через C pool + `asyncio.loop.add_reader()`
- [x] Async compare_archive и compare_dir_urls через C pool (без обёрток)
- [x] Строительные блоки libcurl multi: `async_curl.c` для будущего неблокирующего HTTP
- [x] Тесты: async-эквиваленты всех sync-тестов
- [x] Тесты: конкурентные async-операции

**Результат:** `await komparu.aio.compare()` и все async-варианты работают.

## Фаза 6: Мульти-версии и Free-Threading

**Цель:** Полная матрица версий Python, free-threaded сборки.

- [ ] CI-матрица: Python 3.12, 3.13, 3.14, main
- [ ] Free-threaded сборки: 3.13t, 3.14t
- [ ] `Py_mod_gil` слот, условная компиляция `Py_GIL_DISABLED`
- [ ] Аудит потокобезопасности C-кода
- [ ] Тестирование JIT-сборки
- [ ] Матрица платформ: Linux, macOS, Windows
- [ ] Конфигурация cibuildwheel для всех вариантов

**Результат:** Все тесты проходят на всех версиях Python и платформах.

## Фаза 7: Релиз

**Цель:** Production-ready релиз на PyPI.

- [x] README.md (английский), README.ru.md (русский)
- [x] CLAUDE.md
- [ ] reST-докстринги на всех публичных элементах API
- [ ] Type stubs / py.typed
- [x] Набор бенчмарков с графиками (Go, Rust, filecmp, cmp, hashlib)
- [ ] Dockerfile
- [ ] LICENSE (MIT)
- [ ] Workflow публикации на PyPI
- [ ] Релиз v0.1.0

**Результат:** `pip install komparu` работает. Документация готова.
