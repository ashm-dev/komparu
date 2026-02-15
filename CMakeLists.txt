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
    src/_core/curl_share.c
    src/_core/reader_archive.c
    src/_core/dirwalk.c
    src/_core/pool.c
    src/_core/async_task.c
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

if(WIN32)
    target_link_libraries(_core PRIVATE ws2_32)
endif()

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
# 4.5. Performance Optimizations
#
# -march=native is only used for local source builds (pip install -e .).
# When building wheels via cibuildwheel, we skip it to produce portable
# binaries that run on any CPU of the target architecture.
# Sanitizer builds skip aggressive opts to preserve diagnostic accuracy.
# =============================================================================

if(NOT KOMPARU_SANITIZER)
    if(MSVC)
        target_compile_options(_core PRIVATE /O2 /Ob3 /GL /Gw /Gy)
        target_link_options(_core PRIVATE /LTCG /OPT:REF /OPT:ICF)
    else()
        target_compile_options(_core PRIVATE
            -O3
            -fomit-frame-pointer
            -funroll-loops
            -fstrict-aliasing
            -fno-semantic-interposition
            -pipe
            -DNDEBUG
        )

        # -march=native + -mtune=native only for local builds, not wheels
        if(NOT DEFINED ENV{CIBUILDWHEEL})
            target_compile_options(_core PRIVATE
                -march=native
                -mtune=native
            )
        endif()

        # LTO: -flto=full for clang (whole-module), -flto for gcc
        if(CMAKE_C_COMPILER_ID STREQUAL "Clang" OR CMAKE_C_COMPILER_ID STREQUAL "AppleClang")
            target_compile_options(_core PRIVATE -flto=full)
            target_link_options(_core PRIVATE -flto=full)
            # Use lld for faster linking + better LTO (if available)
            find_program(LLD_FOUND "ld.lld")
            if(LLD_FOUND)
                target_link_options(_core PRIVATE -fuse-ld=lld)
            endif()
        elseif(CMAKE_C_COMPILER_ID STREQUAL "GNU")
            target_compile_options(_core PRIVATE -flto)
            target_link_options(_core PRIVATE -flto)
        endif()
    endif()
else()
    # Sanitizer builds: -O1 preserves enough debug info while catching bugs
    if(NOT MSVC)
        target_compile_options(_core PRIVATE -O1 -g)
    endif()
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
else()
    # Ensure 64-bit file offsets on 32-bit Linux
    target_compile_definitions(_core PRIVATE
        _FILE_OFFSET_BITS=64
    )
endif()

# NOTE: io_uring (Linux) and kqueue (macOS) defines removed — not used by
# current async implementation (C thread pool + eventfd/pipe model).

# =============================================================================
# 6. Sanitizers (opt-in via -DKOMPARU_SANITIZER=address|undefined|thread|memory)
# =============================================================================

set(KOMPARU_SANITIZER "" CACHE STRING "Enable sanitizer (address, undefined, thread, memory)")

if(KOMPARU_SANITIZER)
    if(KOMPARU_SANITIZER STREQUAL "address")
        target_compile_options(_core PRIVATE -fsanitize=address -fno-omit-frame-pointer)
        target_link_options(_core PRIVATE -fsanitize=address)
    elseif(KOMPARU_SANITIZER STREQUAL "undefined")
        target_compile_options(_core PRIVATE -fsanitize=undefined -fno-omit-frame-pointer)
        target_link_options(_core PRIVATE -fsanitize=undefined)
    elseif(KOMPARU_SANITIZER STREQUAL "thread")
        target_compile_options(_core PRIVATE -fsanitize=thread -fno-omit-frame-pointer)
        target_link_options(_core PRIVATE -fsanitize=thread)
    elseif(KOMPARU_SANITIZER STREQUAL "memory")
        target_compile_options(_core PRIVATE -fsanitize=memory -fno-omit-frame-pointer)
        target_link_options(_core PRIVATE -fsanitize=memory)
    else()
        message(FATAL_ERROR "Unknown sanitizer: ${KOMPARU_SANITIZER}")
    endif()
    message(STATUS "Sanitizer enabled: ${KOMPARU_SANITIZER}")
endif()

# =============================================================================
# 7. Installation
# =============================================================================

# Install the extension module into the komparu package directory
install(TARGETS _core DESTINATION komparu)
