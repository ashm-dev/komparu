/**
 * reader_archive.c — Archive reader and comparison using libarchive.
 *
 * Strategy:
 * - Stream-based: no disk extraction, entries read into memory
 * - Archive bomb protection: max decompressed size, compression ratio,
 *   max entries, max entry name length
 * - Path sanitization: reject absolute paths, .. traversal
 * - Comparison: read both archives into sorted entry lists, merge-compare
 *
 * Supported formats: tar, zip, cpio, 7z, xar, etc. (via libarchive)
 * Supported filters: gzip, bzip2, xz, zstd, lz4, etc.
 */

#include "reader_archive.h"
#include "compare.h"
#include <archive.h>
#include <archive_entry.h>
#include <stdlib.h>
#include <string.h>

static _Thread_local char archive_errbuf[512];

/* =========================================================================
 * Archive bomb limits (defaults, overridable via config)
 * ========================================================================= */

#define DEFAULT_MAX_DECOMPRESSED   ((int64_t)1024 * 1024 * 1024)  /* 1 GB */
#define DEFAULT_MAX_RATIO          200
#define DEFAULT_MAX_ENTRIES        100000
#define DEFAULT_MAX_NAME_LENGTH    4096

/* =========================================================================
 * Path sanitization — reject dangerous entry names
 * ========================================================================= */

static bool is_safe_path(const char *path) {
    if (!path || path[0] == '\0') return false;

    /* Reject absolute paths */
    if (path[0] == '/') return false;

    /* Reject .. traversal */
    const char *p = path;
    while (*p) {
        if (p[0] == '.' && p[1] == '.') {
            if (p[2] == '\0' || p[2] == '/') return false;
        }
        /* Advance to next path component */
        while (*p && *p != '/') p++;
        while (*p == '/') p++;
    }

    return true;
}

/* Normalize path: strip leading ./ and collapse multiple slashes */
static char *normalize_path(const char *path) {
    /* Skip leading ./ */
    while (path[0] == '.' && path[1] == '/') {
        path += 2;
        while (*path == '/') path++;
    }

    char *out = strdup(path);
    if (!out) return NULL;

    /* Remove trailing / */
    size_t len = strlen(out);
    while (len > 0 && out[len - 1] == '/') {
        out[--len] = '\0';
    }

    return out;
}

/* =========================================================================
 * In-memory archive entry storage for comparison
 * ========================================================================= */

typedef struct {
    char *name;
    uint8_t *data;
    size_t size;
} entry_data_t;

typedef struct {
    entry_data_t *entries;
    size_t count;
    size_t capacity;
} entry_list_t;

static void entry_list_free(entry_list_t *list) {
    if (!list) return;
    for (size_t i = 0; i < list->count; i++) {
        free(list->entries[i].name);
        free(list->entries[i].data);
    }
    free(list->entries);
    list->entries = NULL;
    list->count = 0;
    list->capacity = 0;
}

static int entry_list_append(entry_list_t *list, const char *name, const uint8_t *data, size_t size) {
    if (list->count >= list->capacity) {
        size_t new_cap = list->capacity ? list->capacity * 2 : 64;
        entry_data_t *tmp = realloc(list->entries, new_cap * sizeof(entry_data_t));
        if (!tmp) return -1;
        list->entries = tmp;
        list->capacity = new_cap;
    }
    entry_data_t *e = &list->entries[list->count];
    e->name = strdup(name);
    if (!e->name) return -1;

    if (size > 0) {
        e->data = malloc(size);
        if (!e->data) {
            free(e->name);
            return -1;
        }
        memcpy(e->data, data, size);
    } else {
        e->data = NULL;
    }
    e->size = size;
    list->count++;
    return 0;
}

static int entry_cmp(const void *a, const void *b) {
    const entry_data_t *ea = (const entry_data_t *)a;
    const entry_data_t *eb = (const entry_data_t *)b;
    return strcmp(ea->name, eb->name);
}

/* =========================================================================
 * Read all entries from an archive file into memory
 * ========================================================================= */

static int read_archive_entries(
    const char *path,
    entry_list_t *out,
    int64_t max_decompressed_size,
    int max_compression_ratio,
    int64_t max_entries,
    int64_t max_entry_name_length,
    const char **err_msg
) {
    memset(out, 0, sizeof(*out));

    /* Apply defaults when limits are disabled (0 or negative) */
    if (max_decompressed_size <= 0) max_decompressed_size = DEFAULT_MAX_DECOMPRESSED;
    if (max_compression_ratio <= 0) max_compression_ratio = DEFAULT_MAX_RATIO;
    if (max_entries <= 0)           max_entries = DEFAULT_MAX_ENTRIES;
    if (max_entry_name_length <= 0) max_entry_name_length = DEFAULT_MAX_NAME_LENGTH;

    struct archive *a = archive_read_new();
    if (!a) {
        *err_msg = "failed to create archive reader";
        return -1;
    }

    archive_read_support_filter_all(a);
    archive_read_support_format_all(a);

    int rc = archive_read_open_filename(a, path, 65536);
    if (rc != ARCHIVE_OK) {
        snprintf(archive_errbuf, sizeof(archive_errbuf),
                 "cannot open archive: %s", archive_error_string(a));
        *err_msg = archive_errbuf;
        archive_read_free(a);
        return -1;
    }

    int64_t total_decompressed = 0;
    int64_t total_compressed = 0;
    int64_t entry_count = 0;

    struct archive_entry *entry;
    while (archive_read_next_header(a, &entry) == ARCHIVE_OK) {
        /* Skip non-regular files (dirs, symlinks, etc.) */
        if (archive_entry_filetype(entry) != AE_IFREG) {
            archive_read_data_skip(a);
            continue;
        }

        entry_count++;

        /* Bomb check: max entries */
        if (entry_count > max_entries) {
            snprintf(archive_errbuf, sizeof(archive_errbuf),
                     "archive bomb: too many entries (>%lld)", (long long)max_entries);
            *err_msg = archive_errbuf;
            goto bomb;
        }

        const char *raw_name = archive_entry_pathname(entry);
        if (!raw_name) {
            archive_read_data_skip(a);
            continue;
        }

        /* Bomb check: entry name length */
        size_t name_len = strlen(raw_name);
        if ((int64_t)name_len > max_entry_name_length) {
            snprintf(archive_errbuf, sizeof(archive_errbuf),
                     "archive bomb: entry name too long (%zu > %lld)",
                     name_len, (long long)max_entry_name_length);
            *err_msg = archive_errbuf;
            goto bomb;
        }

        /* Path sanitization */
        char *safe_name = normalize_path(raw_name);
        if (!safe_name) {
            *err_msg = "out of memory";
            goto fail;
        }

        if (!is_safe_path(safe_name)) {
            free(safe_name);
            archive_read_data_skip(a);
            continue;  /* Skip unsafe paths silently */
        }

        /* Read entry data in chunks */
        int64_t entry_size = archive_entry_size(entry);
        if (entry_size < 0) entry_size = 0;

        /* Bomb check: decompressed size of this entry */
        if (total_decompressed + entry_size > max_decompressed_size) {
            snprintf(archive_errbuf, sizeof(archive_errbuf),
                     "archive bomb: decompressed size exceeds %lld bytes",
                     (long long)max_decompressed_size);
            *err_msg = archive_errbuf;
            free(safe_name);
            goto bomb;
        }

        uint8_t *data = NULL;
        size_t data_len = 0;
        size_t data_cap = 0;

        if (entry_size > 0) {
            /* Known size — pre-allocate */
            data_cap = (size_t)entry_size;
            data = malloc(data_cap);
            if (!data) {
                free(safe_name);
                *err_msg = "out of memory";
                goto fail;
            }
        }

        /* Read data blocks */
        const void *block;
        size_t block_size;
        int64_t block_offset;

        int read_rc;
        while ((read_rc = archive_read_data_block(a, &block, &block_size, &block_offset)) == ARCHIVE_OK) {
            if (block_size == 0) continue;

            /* Integer overflow check */
            if (block_size > SIZE_MAX - data_len) {
                free(data);
                free(safe_name);
                *err_msg = "archive entry too large (size overflow)";
                goto fail;
            }
            size_t needed = data_len + block_size;

            /* Bomb check: running total */
            total_decompressed += (int64_t)block_size;
            if (total_decompressed > max_decompressed_size) {
                snprintf(archive_errbuf, sizeof(archive_errbuf),
                         "archive bomb: decompressed size exceeds %lld bytes",
                         (long long)max_decompressed_size);
                *err_msg = archive_errbuf;
                free(data);
                free(safe_name);
                goto bomb;
            }

            /* Grow buffer if needed */
            if (needed > data_cap) {
                size_t new_cap = data_cap ? data_cap * 2 : 4096;
                if (new_cap < needed) new_cap = needed;
                uint8_t *tmp = realloc(data, new_cap);
                if (!tmp) {
                    free(data);
                    free(safe_name);
                    *err_msg = "out of memory";
                    goto fail;
                }
                data = tmp;
                data_cap = new_cap;
            }

            memcpy(data + data_len, block, block_size);
            data_len += block_size;
        }

        /* Check if loop ended due to error (not EOF) */
        if (read_rc != ARCHIVE_EOF && read_rc != ARCHIVE_OK) {
            snprintf(archive_errbuf, sizeof(archive_errbuf),
                     "archive read error: %s", archive_error_string(a));
            *err_msg = archive_errbuf;
            free(data);
            free(safe_name);
            goto fail;
        }

        /* Bomb check: compression ratio */
        total_compressed = archive_filter_bytes(a, -1);
        if (total_compressed > 0 &&
            total_decompressed / total_compressed > max_compression_ratio) {
            snprintf(archive_errbuf, sizeof(archive_errbuf),
                     "archive bomb: compression ratio exceeds %d:1",
                     max_compression_ratio);
            *err_msg = archive_errbuf;
            free(data);
            free(safe_name);
            goto bomb;
        }

        /* Store entry */
        if (entry_list_append(out, safe_name, data, data_len) != 0) {
            free(data);
            free(safe_name);
            *err_msg = "out of memory";
            goto fail;
        }

        free(data);
        free(safe_name);
    }

    /* Sort entries by name for merge comparison */
    if (out->count > 1) {
        qsort(out->entries, out->count, sizeof(entry_data_t), entry_cmp);
    }

    archive_read_close(a);
    archive_read_free(a);
    return 0;

bomb:
fail:
    entry_list_free(out);
    archive_read_close(a);
    archive_read_free(a);
    return -1;
}

/* =========================================================================
 * Archive comparison — sorted merge of two entry lists
 * ========================================================================= */

komparu_dir_result_t *komparu_compare_archives(
    const char *path_a,
    const char *path_b,
    size_t chunk_size,
    int64_t max_decompressed_size,
    int max_compression_ratio,
    int64_t max_entries,
    int64_t max_entry_name_length,
    const char **err_msg
) {
    (void)chunk_size; /* entries are in-memory, memcmp is used directly */

    entry_list_t list_a = {0};
    entry_list_t list_b = {0};

    if (read_archive_entries(path_a, &list_a,
            max_decompressed_size, max_compression_ratio,
            max_entries, max_entry_name_length, err_msg) != 0) {
        return NULL;
    }

    if (read_archive_entries(path_b, &list_b,
            max_decompressed_size, max_compression_ratio,
            max_entries, max_entry_name_length, err_msg) != 0) {
        entry_list_free(&list_a);
        return NULL;
    }

    komparu_dir_result_t *result = komparu_dir_result_new();
    if (!result) {
        *err_msg = "out of memory";
        entry_list_free(&list_a);
        entry_list_free(&list_b);
        return NULL;
    }

    /* Sorted merge */
    size_t i = 0, j = 0;
    while (i < list_a.count && j < list_b.count) {
        int cmp = strcmp(list_a.entries[i].name, list_b.entries[j].name);

        if (cmp < 0) {
            if (komparu_dir_result_add_only_left(result, list_a.entries[i].name) != 0) {
                *err_msg = "out of memory";
                goto merge_fail;
            }
            i++;
        } else if (cmp > 0) {
            if (komparu_dir_result_add_only_right(result, list_b.entries[j].name) != 0) {
                *err_msg = "out of memory";
                goto merge_fail;
            }
            j++;
        } else {
            /* Same entry name — compare data */
            entry_data_t *ea = &list_a.entries[i];
            entry_data_t *eb = &list_b.entries[j];

            if (ea->size != eb->size) {
                if (komparu_dir_result_add_diff(result, ea->name, KOMPARU_DIFF_SIZE) != 0) {
                    *err_msg = "out of memory";
                    goto merge_fail;
                }
            } else if (ea->size > 0 && memcmp(ea->data, eb->data, ea->size) != 0) {
                if (komparu_dir_result_add_diff(result, ea->name, KOMPARU_DIFF_CONTENT) != 0) {
                    *err_msg = "out of memory";
                    goto merge_fail;
                }
            }
            /* else: both empty or identical */

            i++;
            j++;
        }
    }

    while (i < list_a.count) {
        if (komparu_dir_result_add_only_left(result, list_a.entries[i].name) != 0) {
            *err_msg = "out of memory";
            goto merge_fail;
        }
        i++;
    }

    while (j < list_b.count) {
        if (komparu_dir_result_add_only_right(result, list_b.entries[j].name) != 0) {
            *err_msg = "out of memory";
            goto merge_fail;
        }
        j++;
    }

    entry_list_free(&list_a);
    entry_list_free(&list_b);
    return result;

merge_fail:
    entry_list_free(&list_a);
    entry_list_free(&list_b);
    komparu_dir_result_free(result);
    return NULL;
}

/* =========================================================================
 * Iterator API (for future use / streaming access)
 * ========================================================================= */

struct komparu_archive_iter {
    struct archive *a;
    char *read_buf;
    size_t read_buf_size;
};

komparu_archive_iter_t *komparu_archive_iter_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
) {
    (void)inner_reader;
    *err_msg = "archive iterator from reader not yet implemented (use file paths)";
    return NULL;
}

komparu_reader_t *komparu_archive_iter_next(
    komparu_archive_iter_t *iter,
    const char **entry_name,
    const char **err_msg
) {
    (void)iter;
    (void)entry_name;
    *err_msg = "archive iterator not yet implemented";
    return NULL;
}

void komparu_archive_iter_close(komparu_archive_iter_t *iter) {
    (void)iter;
}

/* Stub: single-entry reader from archive (not needed for comparison) */
komparu_reader_t *komparu_reader_archive_open(
    komparu_reader_t *inner_reader,
    const char **err_msg
) {
    (void)inner_reader;
    *err_msg = "single-entry archive reader not yet implemented";
    return NULL;
}
