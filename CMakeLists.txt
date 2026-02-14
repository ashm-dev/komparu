cmake_minimum_required(VERSION 3.25)

project(komparu
    LANGUAGES C
    VERSION 0.1.0
    DESCRIPTION "Ultra-fast file comparison library"
)

# =============================================================================
# 1. C23 Standard Detection
# =============================================================================

include(CheckCCompilerFlag)
check_c_compiler_flag("-std=c23" COMPILER_SUPPORTS_C23)
check_c_compiler_flag("-std=c2x" COMPILER_SUPPORTS_C2X)

if(COMPILER_SUPPORTS_C23)
    set(CMAKE_C_STANDARD 23)
    set(CMAKE_C_STANDARD_REQUIRED ON)
elseif(COMPILER_SUPPORTS_C2X)
    message(STATUS "Compiler does not support -std=c23, falling back to -std=c2x")
    set(CMAKE_C_STANDARD 23)
    set(CMAKE_C_STANDARD_REQUIRED OFF)
    add_compile_options("-std=c2x")
else()
    message(FATAL_ERROR "Compiler does not support C23 or C2x. GCC 13+ or Clang 18+ required.")
endif()

set(CMAKE_C_EXTENSIONS OFF)

# Hidden visibility by default — essential for Python extensions
set(CMAKE_C_VISIBILITY_PRESET hidden)

# =============================================================================
# 2. Dependencies
# =============================================================================

# Threads (pthreads on Linux/macOS, Windows threads handled via Win32 API)
set(CMAKE_THREAD_PREFER_PTHREAD TRUE)
set(THREADS_PREFER_PTHREAD_FLAG TRUE)
find_package(Threads REQUIRED)

# Python — scikit-build-core provides this automatically
find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)

# libcurl
find_package(CURL REQUIRED)

# libarchive
find_package(LibArchive REQUIRED)

# =============================================================================
# 3. C Extension Target: komparu._core
# =============================================================================

set(KOMPARU_CORE_SOURCES
    src/_core/module.c
    src/_core/compare.c
    src/_core/reader_file.c
    src/_core/reader_http.c
    src/_core/reader_archive.c
    src/_core/dirwalk.c
    src/_core/pool.c
)

python_add_library(_core MODULE ${KOMPARU_CORE_SOURCES})

target_include_directories(_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src/_core
)

target_link_libraries(_core PRIVATE
    Python::Module
    CURL::libcurl
    LibArchive::LibArchive
    Threads::Threads
)

# =============================================================================
# 4. Compiler Warnings
# =============================================================================

if(MSVC)
    target_compile_options(_core PRIVATE /W4)
else()
    target_compile_options(_core PRIVATE
        -Wall -Wextra -Wpedantic
        -Wno-unused-parameter
        -Wstrict-prototypes
        -Wshadow
    )
endif()

# =============================================================================
# 5. Platform-Specific Definitions
# =============================================================================

if(WIN32)
    target_compile_definitions(_core PRIVATE
        _CRT_SECURE_NO_WARNINGS
        WIN32_LEAN_AND_MEAN
        NOMINMAX
    )
endif()

if(APPLE)
    # macOS: use kqueue for async file I/O
    target_compile_definitions(_core PRIVATE KOMPARU_USE_KQUEUE=1)
elseif(UNIX AND NOT APPLE)
    # Linux: use io_uring for async file I/O (if available)
    target_compile_definitions(_core PRIVATE KOMPARU_USE_IO_URING=1)
endif()

# =============================================================================
# 6. Installation
# =============================================================================

# Install the extension module into the komparu package directory
install(TARGETS _core DESTINATION komparu)
