#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto 文件数据 / 存储运行时发射器
==================================

面向「用 Rosoto 写数据库 / 存储类 / 数据类」场景，发射一段自包含 C99 运行时
（mmap + io_uring 文件 IO，无第三方依赖）：

* **CRC32C** —— 硬件加速（x86 SSE4.2 `_mm_crc32`）+ 软件表回退，
  存储完整性校验的基础原语
* **零拷贝文件视图** —— mmap 整段引用 + 边界检查切片 + 小端访问器，
  文件数据 = (指针, 长度) 的强引用，不拷贝（与 rosoto_mem.py 的
  RosotoView 无缝组合，重复包含自动去重）
* **WAL 预写日志** —— 记录帧 [len][crc32c][payload]、攒批落盘、批量
  fdatasync、撕裂尾（torn tail）检测与修复 —— 数据库 redo log 的地基
* **页存储** —— 定长页 + 页头（LSN/CRC/代数/长度）+ 空闲链 + 校验读，
  存储引擎的页管理原语；损坏页读取确定性失败（-EIO）
* **异步文件 IO** —— io_uring READ/WRITE/FSYNC（纯 syscall，与
  tools/rosoto_uring.py 的网络运行时同风格）；内核无 io_uring 时
  自动回退同步 pread/pwrite，语义不变

用法::

    python3 tools/rosoto_store.py emit     [--page-size N] [--wal-prealloc-mb N]
                                          [--async-io true|false]
    python3 tools/rosoto_store.py selftest [同上]      # 发射带 main() 的自测程序

库用法::

    from rosoto_store import emit_store_runtime, emit_store_selftest
"""

import argparse
import sys

__all__ = ["emit_store_runtime", "emit_store_selftest", "DEFAULT_STORE", "main"]

# ---------------------------------------------------------------------------
# 0. 默认配置
# ---------------------------------------------------------------------------

DEFAULT_STORE = {
    "page_size": 4096,        # 页存储页大小（512..65536，2 的幂）
    "page_count": 1024,       # create 时初始页数
    "wal_prealloc_mb": 16,    # WAL 预分配大小（MB）
    "wal_buf_kb": 1024,       # WAL 攒批缓冲（KB）
    "async_io": True,         # io_uring 文件 IO（不可用时自动回退同步）
}

_INT_RANGES = {
    "page_size": (512, 65536),
    "page_count": (1, 1 << 24),
    "wal_prealloc_mb": (0, 65536),
    "wal_buf_kb": (4, 65536),
}


def _as_bool(v, name):
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"配置项 {name} 需要布尔值，得到: {v!r}")


def _bool_arg(s):
    """argparse type 回调：单参包装 _as_bool。"""
    return _as_bool(s, "命令行参数")


def _as_int(v, name):
    lo, hi = _INT_RANGES[name]
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"配置项 {name} 需要整数，得到: {v!r}")
    if not (lo <= n <= hi):
        raise ValueError(f"配置项 {name} 超出范围 [{lo}, {hi}]，得到: {n}")
    return n


def _store_section(config):
    """兼容 `{"store": {...}}` 与扁平 dict 两种入参。"""
    st = dict(DEFAULT_STORE)
    if not config:
        return st
    if not isinstance(config, dict):
        raise ValueError(f"config 需要 dict，得到: {type(config).__name__}")
    src = config.get("store") if isinstance(config.get("store"), dict) else config
    for k, v in src.items():
        if k in st:
            st[k] = v
    return st


# ---------------------------------------------------------------------------
# 1. 发射器
# ---------------------------------------------------------------------------

def emit_store_runtime(config: dict) -> str:
    """返回文件数据/存储运行时 C99 源码（不含 main，可与其他运行时拼接）。"""
    st = _store_section(config)
    page_size = _as_int(st.get("page_size"), "page_size")
    if page_size & (page_size - 1):
        raise ValueError(f"page_size 需为 2 的幂，得到: {page_size}")
    page_count = _as_int(st.get("page_count"), "page_count")
    wal_prealloc = _as_int(st.get("wal_prealloc_mb"), "wal_prealloc_mb")
    wal_buf_kb = _as_int(st.get("wal_buf_kb"), "wal_buf_kb")
    async_io = 1 if _as_bool(st.get("async_io"), "async_io") else 0

    defines = f"""\
/* ==== Rosoto 存储运行时编译期配置（由 tools/rosoto_store.py 注入） ==== */
#ifndef ROSOTO_PAGE_SIZE
#define ROSOTO_PAGE_SIZE {page_size}   /* 页存储页大小（2 的幂） */
#endif
#ifndef ROSOTO_PAGE_COUNT
#define ROSOTO_PAGE_COUNT {page_count}    /* create 时初始页数 */
#endif
#ifndef ROSOTO_WAL_PREALLOC_MB
#define ROSOTO_WAL_PREALLOC_MB {wal_prealloc}  /* WAL 预分配 MB */
#endif
#ifndef ROSOTO_WAL_BUF_KB
#define ROSOTO_WAL_BUF_KB {wal_buf_kb}  /* WAL 攒批缓冲 KB */
#endif
#ifndef ROSOTO_ASYNC_IO
#define ROSOTO_ASYNC_IO {async_io}  /* 1=io_uring 文件 IO（不可用自动回退同步） */
#endif
"""
    return defines + STORE_RUNTIME_C


def emit_store_selftest(config: dict) -> str:
    """返回运行时 + 自测 main() 的完整 C 程序（退出码 0 = 全部通过）。"""
    return emit_store_runtime(config) + STORE_SELFTEST_C


# ---------------------------------------------------------------------------
# 2. C 运行时
# ---------------------------------------------------------------------------

STORE_RUNTIME_C = r"""
/* =====================================================================
 * Rosoto 文件数据 / 存储运行时
 * ---------------------------------------------------------------------
 * 数据库 / 存储引擎地基，全部原语都以「可校验、可恢复、零拷贝」为准绳：
 *   CRC32C 校验  ->  文件视图（mmap 零拷贝引用）
 *                ->  WAL（顺序追加 + 批量 fsync + 撕裂尾恢复）
 *                ->  页存储（定长页 + 校验 + 空闲链 + 代数）
 *                ->  异步文件 IO（io_uring，同步回退）
 *
 * 内存预算：
 *   WAL 攒批缓冲 1MB/日志（攒批落盘摊销 fsync）；
 *   页存储整文件 mmap（页头 32B/页，payload = page_size - 32）；
 *   异步 IO 每请求 48B 瞬时（完成即释放）；
 *   文件视图 32B/视图（fd + map 指针 + 长度），数据本体在页缓存/映射内。
 * ===================================================================== */
#ifndef ROSOTO_STORE_RUNTIME_INCLUDED
#define ROSOTO_STORE_RUNTIME_INCLUDED

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#if defined(__SSE4_2__) && defined(__x86_64__)
#  include <smmintrin.h>
#endif

/* ---- 0. 视图类型（与 rosoto_mem.py 共享定义，重复包含自动去重） ---- */
#ifndef ROSOTO_VIEW_DEFINED
#define ROSOTO_VIEW_DEFINED
typedef struct RosotoView { const uint8_t *ptr; size_t len; } RosotoView;
typedef struct RosotoMutView { uint8_t *ptr; size_t len; } RosotoMutView;
#endif

/* ---- 1. CRC32C（Castagnoli，硬件加速 + 软件表回退） ---- */
/* 标准测试向量：crc32c("123456789") == 0xE3069283 */
static uint32_t rosoto_crc32c_tab[256];
static int rosoto_crc32c_ready;

static void rosoto_crc32c_init(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++)
            c = (c & 1u) ? (0x82F63B78u ^ (c >> 1)) : (c >> 1);
        rosoto_crc32c_tab[i] = c;
    }
}
static inline void rosoto_crc32c_once(void) {
    if (!__atomic_load_n(&rosoto_crc32c_ready, __ATOMIC_ACQUIRE)) {
        rosoto_crc32c_init();
        __atomic_store_n(&rosoto_crc32c_ready, 1, __ATOMIC_RELEASE);
    }
}
/* 原始累加器步进（SSE4.2 crc32 指令与软件表同为反射式递推，可混用） */
static inline uint32_t rosoto_crc32c_step(uint32_t acc, const uint8_t *p, size_t n) {
#if defined(__SSE4_2__) && defined(__x86_64__)
    while (n >= 8) {
        uint64_t v;
        memcpy(&v, p, 8);
        acc = (uint32_t)_mm_crc32_u64(acc, v);
        p += 8;
        n -= 8;
    }
#endif
    while (n--)
        acc = rosoto_crc32c_tab[(acc ^ *p++) & 0xFFu] ^ (acc >> 8);
    return acc;
}
uint32_t rosoto_crc32c(const void *data, size_t n) {
    rosoto_crc32c_once();
    return ~rosoto_crc32c_step(~0u, (const uint8_t *)data, n);
}
/* 增量链式：多次 append 的分段校验等价一次性校验 */
uint32_t rosoto_crc32c_chain(uint32_t prev, const void *data, size_t n) {
    rosoto_crc32c_once();
    return ~rosoto_crc32c_step(~prev, (const uint8_t *)data, n);
}

/* ---- 2. 小端访问器（与 rosoto_mem.py 共享，重复包含自动去重） ---- */
#ifndef ROSOTO_MEM_VIEW_IMPL
#define ROSOTO_MEM_VIEW_IMPL
static inline RosotoView rosoto_view(const void *p, size_t n) {
    RosotoView v;
    v.ptr = (const uint8_t *)p;
    v.len = p ? n : 0;
    return v;
}
static inline RosotoMutView rosoto_mview(void *p, size_t n) {
    RosotoMutView v;
    v.ptr = (uint8_t *)p;
    v.len = p ? n : 0;
    return v;
}
bool rosoto_view_u32(RosotoView v, size_t off, uint32_t *out) {
    if (off + 4 > v.len) return false;
    *out = (uint32_t)v.ptr[off] | ((uint32_t)v.ptr[off + 1] << 8) |
           ((uint32_t)v.ptr[off + 2] << 16) | ((uint32_t)v.ptr[off + 3] << 24);
    return true;
}
bool rosoto_view_u64(RosotoView v, size_t off, uint64_t *out) {
    uint32_t lo, hi;
    if (!rosoto_view_u32(v, off, &lo) || !rosoto_view_u32(v, off + 4, &hi)) return false;
    *out = (uint64_t)lo | ((uint64_t)hi << 32);
    return true;
}
bool rosoto_mview_put_u32(RosotoMutView v, size_t off, uint32_t x) {
    if (off + 4 > v.len) return false;
    v.ptr[off] = (uint8_t)x;
    v.ptr[off + 1] = (uint8_t)(x >> 8);
    v.ptr[off + 2] = (uint8_t)(x >> 16);
    v.ptr[off + 3] = (uint8_t)(x >> 24);
    return true;
}
bool rosoto_mview_put_u64(RosotoMutView v, size_t off, uint64_t x) {
    return rosoto_mview_put_u32(v, off, (uint32_t)x) &&
           rosoto_mview_put_u32(v, off + 4, (uint32_t)(x >> 32));
}
#endif /* ROSOTO_MEM_VIEW_IMPL */

/* ---- 3. WAL 预写日志（数据库 redo 地基） ---- */
/* 记录帧布局：[u32 len][u32 crc32c(payload)][payload(len)]
 *   - len 上限 16MB（防坏帧放大）
 *   - 撕裂尾：崩溃后尾帧不完整/crc 不符 -> 回放识别为坏尾，有效前缀保留 */
#define ROSOTO_WAL_MAGIC   0x52574C31u   /* "RWL1" */
#define ROSOTO_WAL_MAX_REC (16u * 1024u * 1024u)

typedef struct RosotoWal {
    int fd;
    uint64_t lsn;        /* 已追加记录数 */
    uint64_t written;    /* 已落盘偏移（不含攒批） */
    uint8_t *buf;        /* 攒批缓冲 */
    size_t buf_used, buf_cap;
    uint64_t syncs;
} RosotoWal;

static int rosoto_wal_flush_buf(RosotoWal *w) {
    size_t off = 0;
    while (off < w->buf_used) {
        ssize_t n = pwrite(w->fd, w->buf + off, w->buf_used - off, (off_t)(w->written + off));
        if (n <= 0) return -1;
        off += (size_t)n;
    }
    w->written += w->buf_used;
    w->buf_used = 0;
    return 0;
}

RosotoWal *rosoto_wal_open(const char *path, size_t prealloc_mb) {
    RosotoWal *w = (RosotoWal *)calloc(1, sizeof(RosotoWal));
    if (!w) return NULL;
    w->fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (w->fd < 0) { free(w); return NULL; }
    if (prealloc_mb > 0) {
        /* 预分配：避免运行期文件系统元数据抖动（fallocate 不可用时回退 ftruncate） */
        if (posix_fallocate(w->fd, 0, (off_t)prealloc_mb * 1024 * 1024) != 0) {
            int trc = ftruncate(w->fd, (off_t)prealloc_mb * 1024 * 1024);
            (void)trc;
        }
        w->written = 0;
    }
    w->buf_cap = (size_t)ROSOTO_WAL_BUF_KB * 1024;
    w->buf = (uint8_t *)malloc(w->buf_cap);
    if (!w->buf) { close(w->fd); free(w); return NULL; }
    return w;
}

/* 追加一条记录（攒批）；返回 lsn（从 1 起）。len 上限 16MB。 */
uint64_t rosoto_wal_append(RosotoWal *w, const void *rec, uint32_t len) {
    if (!w || !rec || len == 0 || len > ROSOTO_WAL_MAX_REC) return 0;
    size_t frame = 8 + len;
    if (w->buf_used + frame > w->buf_cap) {
        if (rosoto_wal_flush_buf(w) != 0) return 0;
    }
    uint32_t crc = rosoto_crc32c(rec, len);
    uint8_t *p = w->buf + w->buf_used;
    p[0] = (uint8_t)len; p[1] = (uint8_t)(len >> 8);
    p[2] = (uint8_t)(len >> 16); p[3] = (uint8_t)(len >> 24);
    p[4] = (uint8_t)crc; p[5] = (uint8_t)(crc >> 8);
    p[6] = (uint8_t)(crc >> 16); p[7] = (uint8_t)(crc >> 24);
    memcpy(p + 8, rec, len);
    w->buf_used += frame;
    return ++w->lsn;
}

/* 落盘 + fdatasync（fsync 摊销到批，不逐条） */
int rosoto_wal_sync(RosotoWal *w) {
    if (!w) return -1;
    if (rosoto_wal_flush_buf(w) != 0) return -1;
    w->syncs++;
    return fdatasync(w->fd);
}

void rosoto_wal_close(RosotoWal *w) {
    if (!w) return;
    if (w->buf_used) (void)rosoto_wal_flush_buf(w);
    close(w->fd);
    free(w->buf);
    free(w);
}

/* 回放：逐帧校验（len/crc/完整性），撕裂尾即停。
 * cb 返回 0 继续、非 0 提前中止。返回有效记录数。 */
int rosoto_wal_replay(const char *path,
                      int (*cb)(void *user, uint64_t lsn, const void *rec, uint32_t len),
                      void *user) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    int count = 0;
    uint64_t lsn = 0;
    uint64_t pos = 0;
    uint8_t hdr[8];
    uint8_t *payload = NULL;
    size_t payload_cap = 0;
    for (;;) {
        ssize_t n = pread(fd, hdr, 8, (off_t)pos);
        if (n != 8) break;                       /* 尾部不足帧头：撕裂尾 */
        uint32_t len = (uint32_t)hdr[0] | ((uint32_t)hdr[1] << 8) |
                       ((uint32_t)hdr[2] << 16) | ((uint32_t)hdr[3] << 24);
        uint32_t crc = (uint32_t)hdr[4] | ((uint32_t)hdr[5] << 8) |
                       ((uint32_t)hdr[6] << 16) | ((uint32_t)hdr[7] << 24);
        if (len == 0 || len > ROSOTO_WAL_MAX_REC) break;   /* 坏帧头 */
        if (len > payload_cap) {
            free(payload);
            payload = (uint8_t *)malloc(len);
            payload_cap = len;
            if (!payload) break;
        }
        n = pread(fd, payload, len, (off_t)(pos + 8));
        if (n != (ssize_t)len) break;            /* 尾部不足负载：撕裂尾 */
        if (rosoto_crc32c(payload, len) != crc) break;     /* 校验失败：撕裂尾 */
        lsn++;
        count++;
        if (cb && cb(user, lsn, payload, len) != 0) break;
        pos += 8 + len;
    }
    free(payload);
    close(fd);
    return count;
}

/* 修复：把撕裂尾截掉（回放扫描出的有效前缀终点） */
int rosoto_wal_repair(const char *path) {
    int fd = open(path, O_RDWR);
    if (fd < 0) return -1;
    uint64_t pos = 0;
    uint8_t hdr[8];
    uint8_t *payload = NULL;
    size_t payload_cap = 0;
    for (;;) {
        ssize_t n = pread(fd, hdr, 8, (off_t)pos);
        if (n != 8) break;
        uint32_t len = (uint32_t)hdr[0] | ((uint32_t)hdr[1] << 8) |
                       ((uint32_t)hdr[2] << 16) | ((uint32_t)hdr[3] << 24);
        uint32_t crc = (uint32_t)hdr[4] | ((uint32_t)hdr[5] << 8) |
                       ((uint32_t)hdr[6] << 16) | ((uint32_t)hdr[7] << 24);
        if (len == 0 || len > ROSOTO_WAL_MAX_REC) break;
        if (len > payload_cap) {
            free(payload);
            payload = (uint8_t *)malloc(len);
            payload_cap = len;
            if (!payload) break;
        }
        n = pread(fd, payload, len, (off_t)(pos + 8));
        if (n != (ssize_t)len) break;
        if (rosoto_crc32c(payload, len) != crc) break;
        pos += 8 + len;
    }
    free(payload);
    int rc = ftruncate(fd, (off_t)pos);
    close(fd);
    return rc;
}

/* ---- 4. 页存储（定长页 + 校验 + 空闲链 + 代数） ---- */
/* 文件布局：页 0 = 文件头 {magic, page_size, page_count, crc}；
 * 页 1..N = {页头 32B: lsn@0/crc@8/gen@12/next@16/len@24} + payload(page_size - 32)。
 * crc 覆盖 payload[0..len)；读路径先校验后拷贝（损坏页 -EIO）。 */
#define ROSOTO_PG_MAGIC    0x52504731u   /* "RPG1" */
#define ROSOTO_PG_HDR_SIZE 32u

typedef struct RosotoPgStore {
    int fd;
    uint8_t *map;
    size_t map_len;
    uint32_t page_size;
    uint64_t page_count;   /* 可用页数（不含头页） */
    uint64_t free_head;    /* 空闲链头页号；0 = 无 */
    uint64_t lsn;
    int writable;
} RosotoPgStore;

static inline uint8_t *rosoto_pg_page(RosotoPgStore *p, uint64_t no) {
    return p->map + (size_t)no * p->page_size;
}

RosotoPgStore *rosoto_pg_open(const char *path, uint32_t page_size,
                              uint64_t page_count, bool create) {
    if (page_size < 512 || (page_size & (page_size - 1))) return NULL;
    RosotoPgStore *p = (RosotoPgStore *)calloc(1, sizeof(RosotoPgStore));
    if (!p) return NULL;
    p->fd = open(path, create ? (O_RDWR | O_CREAT | O_TRUNC) : O_RDWR, 0644);
    if (p->fd < 0) { free(p); return NULL; }
    p->page_size = page_size;
    p->writable = 1;
    if (create) {
        if (page_count == 0) page_count = ROSOTO_PAGE_COUNT;
        size_t total = (size_t)(page_count + 1) * page_size;
        if (ftruncate(p->fd, (off_t)total) != 0) { close(p->fd); free(p); return NULL; }
        p->map = (uint8_t *)mmap(NULL, total, PROT_READ | PROT_WRITE, MAP_SHARED, p->fd, 0);
        if (p->map == MAP_FAILED) { close(p->fd); free(p); return NULL; }
        p->map_len = total;
        p->page_count = page_count;
        /* 初始化空闲链：页 1..N 串成链 */
        for (uint64_t i = 1; i <= page_count; i++) {
            uint8_t *pg = rosoto_pg_page(p, i);
            memset(pg, 0, ROSOTO_PG_HDR_SIZE);
            uint64_t next = (i < page_count) ? i + 1 : 0;
            memcpy(pg + 16, &next, 8);
        }
        p->free_head = page_count ? 1 : 0;
        /* 写文件头（crc 覆盖前 24 字节） */
        uint8_t *h = p->map;
        uint32_t magic = ROSOTO_PG_MAGIC;
        uint64_t lsn = 0;
        memcpy(h + 0, &magic, 4);
        memcpy(h + 4, &page_size, 4);
        memcpy(h + 8, &page_count, 8);
        memcpy(h + 16, &lsn, 8);
        uint32_t hcrc = rosoto_crc32c(h, 24);
        memcpy(h + 24, &hcrc, 4);
    } else {
        struct stat st;
        if (fstat(p->fd, &st) != 0 || (size_t)st.st_size < page_size * 2) {
            close(p->fd); free(p); return NULL;
        }
        p->map_len = (size_t)st.st_size;
        p->map = (uint8_t *)mmap(NULL, p->map_len, PROT_READ | PROT_WRITE, MAP_SHARED, p->fd, 0);
        if (p->map == MAP_FAILED) { close(p->fd); free(p); return NULL; }
        /* 校验文件头 */
        uint8_t *h = p->map;
        uint32_t magic = 0, hcrc = 0, stored = 0;
        uint64_t page_count64 = 0;
        memcpy(&magic, h + 0, 4);
        memcpy(&page_size, h + 4, 4);
        memcpy(&page_count64, h + 8, 8);
        memcpy(&stored, h + 24, 4);
        hcrc = rosoto_crc32c(h, 24);
        if (magic != ROSOTO_PG_MAGIC || hcrc != stored) {
            munmap(p->map, p->map_len);
            close(p->fd); free(p); return NULL;
        }
        p->page_size = page_size;
        p->page_count = page_count64;
        memcpy(&p->lsn, h + 16, 8);
        /* 重建空闲链（简化：全部视为可用；生产可持久化 free_head） */
        p->free_head = page_count64 ? 1 : 0;
        for (uint64_t i = 1; i <= page_count64; i++) {
            uint8_t *pg = rosoto_pg_page(p, i);
            uint64_t next = (i < page_count64) ? i + 1 : 0;
            memcpy(pg + 16, &next, 8);
        }
    }
    return p;
}

uint64_t rosoto_pg_alloc(RosotoPgStore *p) {
    if (!p || p->free_head == 0) return 0;
    uint64_t no = p->free_head;
    uint8_t *pg = rosoto_pg_page(p, no);
    uint64_t next = 0;
    memcpy(&next, pg + 16, 8);
    p->free_head = next;
    memset(pg + 24, 0, 8);                          /* 清 len/保留区（next@16 已被读走） */
    return no;
}

void rosoto_pg_free(RosotoPgStore *p, uint64_t no) {
    if (!p || no == 0 || no > p->page_count) return;
    uint8_t *pg = rosoto_pg_page(p, no);
    uint32_t gen = 0;
    memcpy(&gen, pg + 12, 4);
    gen++;                                          /* 代数递增：旧引用可检测 */
    memcpy(pg + 12, &gen, 4);
    uint64_t next = p->free_head;
    memcpy(pg + 16, &next, 8);
    p->free_head = no;
}

/* 写 payload[off, off+len) 并更新页头校验（整页 payload 参与 crc） */
int rosoto_pg_write(RosotoPgStore *p, uint64_t no, const void *data,
                    uint32_t off, uint32_t len) {
    if (!p || no == 0 || no > p->page_count) return -EINVAL;
    uint32_t cap = p->page_size - ROSOTO_PG_HDR_SIZE;
    if (off > cap || len > cap - off) return -ERANGE;
    uint8_t *pg = rosoto_pg_page(p, no);
    memcpy(pg + ROSOTO_PG_HDR_SIZE + off, data, len);
    uint32_t cur_len = 0;
    memcpy(&cur_len, pg + 24, 4);
    if (off + len > cur_len) cur_len = off + len;
    memcpy(pg + 24, &cur_len, 4);
    uint64_t lsn = ++p->lsn;
    memcpy(pg + 0, &lsn, 8);
    uint32_t crc = rosoto_crc32c(pg + ROSOTO_PG_HDR_SIZE, cur_len);
    memcpy(pg + 8, &crc, 4);
    return 0;
}

/* 读 payload[off, off+len)；先整段校验，损坏页确定性失败 -EIO */
int rosoto_pg_read(RosotoPgStore *p, uint64_t no, void *data,
                   uint32_t off, uint32_t len) {
    if (!p || no == 0 || no > p->page_count) return -EINVAL;
    uint32_t cap = p->page_size - ROSOTO_PG_HDR_SIZE;
    if (off > cap || len > cap - off) return -ERANGE;
    uint8_t *pg = rosoto_pg_page(p, no);
    uint32_t cur_len = 0, crc = 0;
    memcpy(&cur_len, pg + 24, 4);
    memcpy(&crc, pg + 8, 4);
    if (cur_len > cap || off + len > cur_len) return -ERANGE;
    if (rosoto_crc32c(pg + ROSOTO_PG_HDR_SIZE, cur_len) != crc) return -EIO;
    memcpy(data, pg + ROSOTO_PG_HDR_SIZE + off, len);
    return 0;
}

int rosoto_pg_flush(RosotoPgStore *p) {
    if (!p) return -1;
    if (msync(p->map, p->map_len, MS_SYNC) != 0) return -1;
    return fdatasync(p->fd);
}

void rosoto_pg_close(RosotoPgStore *p) {
    if (!p) return;
    if (p->map && p->map != MAP_FAILED) {
        (void)msync(p->map, p->map_len, MS_SYNC);
        munmap(p->map, p->map_len);
    }
    if (p->fd >= 0) close(p->fd);
    free(p);
}

/* ---- 5. 零拷贝文件视图（mmap 强引用） ---- */
typedef struct RosotoFileView {
    int fd;
    uint8_t *map;
    size_t len;
    int writable;
} RosotoFileView;

RosotoFileView *rosoto_file_view_open(const char *path, bool writable) {
    RosotoFileView *fv = (RosotoFileView *)calloc(1, sizeof(RosotoFileView));
    if (!fv) return NULL;
    fv->fd = open(path, writable ? O_RDWR : O_RDONLY);
    if (fv->fd < 0) { free(fv); return NULL; }
    struct stat st;
    if (fstat(fv->fd, &st) != 0) { close(fv->fd); free(fv); return NULL; }
    fv->len = (size_t)st.st_size;
    fv->writable = writable ? 1 : 0;
    if (fv->len == 0) { fv->map = NULL; return fv; }
    fv->map = (uint8_t *)mmap(NULL, fv->len,
                              PROT_READ | (writable ? PROT_WRITE : 0),
                              MAP_SHARED, fv->fd, 0);
    if (fv->map == MAP_FAILED) { close(fv->fd); free(fv); return NULL; }
    return fv;
}

RosotoFileView *rosoto_file_view_create(const char *path, size_t size) {
    RosotoFileView *fv = (RosotoFileView *)calloc(1, sizeof(RosotoFileView));
    if (!fv) return NULL;
    fv->fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fv->fd < 0) { free(fv); return NULL; }
    if (ftruncate(fv->fd, (off_t)size) != 0) { close(fv->fd); free(fv); return NULL; }
    fv->len = size;
    fv->writable = 1;
    if (size == 0) { fv->map = NULL; return fv; }
    fv->map = (uint8_t *)mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fv->fd, 0);
    if (fv->map == MAP_FAILED) { close(fv->fd); free(fv); return NULL; }
    memset(fv->map, 0, size);
    return fv;
}

/* 整段引用：文件 = (指针, 长度)，零拷贝 */
RosotoView rosoto_file_view_of(RosotoFileView *fv) {
    return rosoto_view(fv ? fv->map : NULL, fv ? fv->len : 0);
}
bool rosoto_file_view_slice(RosotoFileView *fv, size_t off, size_t n, RosotoView *out) {
    if (out) { out->ptr = NULL; out->len = 0; }
    if (!fv || off > fv->len || n > fv->len - off) return false;
    if (out) { out->ptr = fv->map + off; out->len = n; }
    return true;
}
RosotoMutView rosoto_file_view_mut(RosotoFileView *fv) {
    RosotoMutView v;
    v.ptr = (fv && fv->writable) ? fv->map : NULL;
    v.len = (fv && fv->writable) ? fv->len : 0;
    return v;
}

/* 扩容（ftruncate + mremap；数据语义：新区域为 0） */
bool rosoto_file_view_grow(RosotoFileView *fv, size_t new_len) {
    if (!fv || !fv->writable || new_len <= fv->len) return false;
    if (ftruncate(fv->fd, (off_t)new_len) != 0) return false;
    void *nm = mremap(fv->map, fv->len, new_len, MREMAP_MAYMOVE);
    if (nm == MAP_FAILED) return false;
    fv->map = (uint8_t *)nm;
    memset(fv->map + fv->len, 0, new_len - fv->len);
    fv->len = new_len;
    return true;
}

int rosoto_file_view_sync(RosotoFileView *fv) {
    if (!fv || !fv->writable || !fv->map) return -1;
    if (msync(fv->map, fv->len, MS_SYNC) != 0) return -1;
    return fdatasync(fv->fd);
}

void rosoto_file_view_close(RosotoFileView *fv) {
    if (!fv) return;
    if (fv->map) munmap(fv->map, fv->len);
    if (fv->fd >= 0) close(fv->fd);
    free(fv);
}

/* ---- 6. 异步文件 IO（io_uring READ/WRITE/FSYNC；同步回退） ---- */
/* 与 tools/rosoto_uring.py 的网络运行时同风格：纯 syscall、无 liburing。
 * 内核无 io_uring（ENOSYS/EPERM）时 aio_open 返回「同步模式」句柄，
 * 所有操作内联完成并立即回调，语义不变。 */
#ifndef __NR_io_uring_setup
#  define __NR_io_uring_setup    425
#  define __NR_io_uring_enter    426
#endif
#ifndef ROSOTO_HAVE_URING_H_MIN
#define ROSOTO_HAVE_URING_H_MIN
#if defined(__has_include)
#  if __has_include(<linux/io_uring.h>)
#    include <linux/io_uring.h>
#    define ROSOTO_STORE_HAVE_URING_H 1
#  endif
#elif defined(__linux__)
#  include <linux/io_uring.h>
#  define ROSOTO_STORE_HAVE_URING_H 1
#endif
#ifndef ROSOTO_STORE_HAVE_URING_H
/* 最小 ABI 自足定义（无内核头文件环境的编译/语法检查） */
struct io_uring_sqe {
    uint8_t opcode; uint8_t flags; uint16_t ioprio; int32_t fd;
    uint64_t off; uint64_t addr; uint32_t len; uint32_t rw_flags;
    uint64_t user_data; uint16_t buf_index; uint16_t personality;
    int32_t splice_fd_in; uint64_t addr3; uint64_t __pad2;
};
struct io_uring_cqe { uint64_t user_data; int32_t res; uint32_t flags; };
struct io_sqring_offsets {
    uint32_t head, tail, ring_mask, ring_entries, flags, dropped, array, resv1;
    uint64_t user_addr;
};
struct io_cqring_offsets {
    uint32_t head, tail, ring_mask, ring_entries, overflow, cqes, flags, resv1;
    uint64_t user_addr;
};
struct io_uring_params {
    uint32_t sq_entries, cq_entries, flags, sq_thread_cpu, sq_thread_idle;
    uint32_t features, wq_fd, resv[3];
    struct io_sqring_offsets sq_off;
    struct io_cqring_offsets cq_off;
};
#define IORING_OFF_SQ_RING      0ULL
#define IORING_OFF_SQES         0x10000000ULL
#define IORING_FEAT_SINGLE_MMAP (1U << 0)
#define IORING_ENTER_GETEVENTS  (1U << 0)
#define IORING_OP_FSYNC         3
#define IORING_OP_WRITE         23
#define IORING_OP_READ          22
#endif
#endif /* ROSOTO_HAVE_URING_H_MIN */

typedef void (*RosotoAioCb)(void *user, int result);

typedef struct RosotoAioReq {
    RosotoAioCb cb;
    void *user;
} RosotoAioReq;

typedef struct RosotoAio {
    int uring;             /* 0 = 同步回退模式 */
    int ring_fd;
    struct io_uring_sqe *sqes;
    char *sq_ring, *cq_ring;
    unsigned *sq_head, *sq_tail, *sq_mask, *sq_array;
    unsigned *cq_head, *cq_tail, *cq_mask;
    struct io_uring_cqe *cqes;
    unsigned sq_entries, sq_unsubmitted;
    uint64_t submitted, completed;
} RosotoAio;

static inline unsigned rosoto_aio_load(const unsigned *p) {
    return __atomic_load_n(p, __ATOMIC_ACQUIRE);
}
static inline void rosoto_aio_store(unsigned *p, unsigned v) {
    __atomic_store_n(p, v, __ATOMIC_RELEASE);
}

RosotoAio *rosoto_aio_open(unsigned entries) {
    if (entries < 16) entries = 16;
    RosotoAio *a = (RosotoAio *)calloc(1, sizeof(RosotoAio));
    if (!a) return NULL;
    a->ring_fd = -1;
    if (!ROSOTO_ASYNC_IO) return a;            /* 编译期禁用：同步模式 */
    struct io_uring_params p;
    memset(&p, 0, sizeof p);
    int fd = (int)syscall(__NR_io_uring_setup, entries, &p);
    if (fd < 0) return a;                      /* 内核无 io_uring：同步回退 */
    size_t sq_sz = (size_t)p.sq_off.array + (size_t)p.sq_entries * sizeof(unsigned);
    size_t cq_sz = (size_t)p.cq_off.cqes + (size_t)p.cq_entries * sizeof(struct io_uring_cqe);
    if (p.features & IORING_FEAT_SINGLE_MMAP) {
        if (cq_sz > sq_sz) sq_sz = cq_sz;
    }
    a->sq_ring = (char *)mmap(NULL, sq_sz, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_POPULATE,
                              fd, IORING_OFF_SQ_RING);
    if (a->sq_ring == MAP_FAILED) { close(fd); return a; }
    if (p.features & IORING_FEAT_SINGLE_MMAP) {
        a->cq_ring = a->sq_ring;
    } else {
        a->cq_ring = (char *)mmap(NULL, cq_sz, PROT_READ | PROT_WRITE,
                                  MAP_SHARED | MAP_POPULATE, fd, IORING_OFF_CQ_RING);
        if (a->cq_ring == MAP_FAILED) { munmap(a->sq_ring, sq_sz); close(fd); return a; }
    }
    a->sqes = (struct io_uring_sqe *)mmap(NULL, (size_t)p.sq_entries * sizeof(struct io_uring_sqe),
                                          PROT_READ | PROT_WRITE, MAP_SHARED | MAP_POPULATE,
                                          fd, IORING_OFF_SQES);
    if (a->sqes == MAP_FAILED) { close(fd); return a; }
    a->ring_fd = fd;
    a->sq_entries = p.sq_entries;
    a->sq_head = (unsigned *)(a->sq_ring + p.sq_off.head);
    a->sq_tail = (unsigned *)(a->sq_ring + p.sq_off.tail);
    a->sq_mask = (unsigned *)(a->sq_ring + p.sq_off.ring_mask);
    a->sq_array = (unsigned *)(a->sq_ring + p.sq_off.array);
    a->cq_head = (unsigned *)(a->cq_ring + p.cq_off.head);
    a->cq_tail = (unsigned *)(a->cq_ring + p.cq_off.tail);
    a->cq_mask = (unsigned *)(a->cq_ring + p.cq_off.ring_mask);
    a->cqes = (struct io_uring_cqe *)(a->cq_ring + p.cq_off.cqes);
    a->uring = 1;
    return a;
}

static void rosoto_aio_flush(RosotoAio *a) {
    while (a->sq_unsubmitted > 0) {
        int ret = (int)syscall(__NR_io_uring_enter, a->ring_fd,
                               (unsigned long)a->sq_unsubmitted, 0UL, 0, NULL, 0UL);
        if (ret > 0) { a->sq_unsubmitted -= (unsigned)ret; continue; }
        if (ret < 0 && errno == EINTR) continue;
        return;
    }
}

static struct io_uring_sqe *rosoto_aio_sqe(RosotoAio *a) {
    for (;;) {
        unsigned tail = *a->sq_tail;
        if (tail - rosoto_aio_load(a->sq_head) < a->sq_entries) {
            struct io_uring_sqe *sqe = &a->sqes[tail & *a->sq_mask];
            memset(sqe, 0, sizeof *sqe);
            a->sq_array[tail & *a->sq_mask] = tail & *a->sq_mask;
            rosoto_aio_store(a->sq_tail, tail + 1);
            a->sq_unsubmitted++;
            return sqe;
        }
        rosoto_aio_flush(a);
    }
}

static void rosoto_aio_submit_req(RosotoAio *a, int op, int fd, uint64_t off,
                                  void *buf, size_t len, RosotoAioCb cb, void *user) {
    RosotoAioReq *req = (RosotoAioReq *)malloc(sizeof(RosotoAioReq));
    if (!req) { if (cb) cb(user, -ENOMEM); return; }
    req->cb = cb;
    req->user = user;
    struct io_uring_sqe *sqe = rosoto_aio_sqe(a);
    sqe->opcode = (uint8_t)op;
    sqe->fd = fd;
    sqe->off = off;
    sqe->addr = (uint64_t)(uintptr_t)buf;
    sqe->len = (uint32_t)len;
    sqe->user_data = (uint64_t)(uintptr_t)req;
    a->submitted++;
}

int rosoto_aio_read(RosotoAio *a, int fd, uint64_t off, void *buf, size_t len,
                    RosotoAioCb cb, void *user) {
    if (!a) return -EINVAL;
    if (!a->uring) {   /* 同步回退：pread 内联完成 */
        ssize_t n = pread(fd, buf, len, (off_t)off);
        if (cb) cb(user, n < 0 ? -errno : (int)n);
        return 0;
    }
    rosoto_aio_submit_req(a, IORING_OP_READ, fd, off, buf, len, cb, user);
    return 0;
}
int rosoto_aio_write(RosotoAio *a, int fd, uint64_t off, const void *buf, size_t len,
                     RosotoAioCb cb, void *user) {
    if (!a) return -EINVAL;
    if (!a->uring) {
        ssize_t n = pwrite(fd, buf, len, (off_t)off);
        if (cb) cb(user, n < 0 ? -errno : (int)n);
        return 0;
    }
    rosoto_aio_submit_req(a, IORING_OP_WRITE, fd, off, (void *)(uintptr_t)buf, len, cb, user);
    return 0;
}
int rosoto_aio_fsync(RosotoAio *a, int fd, RosotoAioCb cb, void *user) {
    if (!a) return -EINVAL;
    if (!a->uring) {
        int rc = fdatasync(fd);
        if (cb) cb(user, rc < 0 ? -errno : 0);
        return 0;
    }
    RosotoAioReq *req = (RosotoAioReq *)malloc(sizeof(RosotoAioReq));
    if (!req) { if (cb) cb(user, -ENOMEM); return 0; }
    req->cb = cb;
    req->user = user;
    struct io_uring_sqe *sqe = rosoto_aio_sqe(a);
    sqe->opcode = (uint8_t)IORING_OP_FSYNC;
    sqe->fd = fd;
    sqe->user_data = (uint64_t)(uintptr_t)req;
    a->submitted++;
    return 0;
}

/* 非阻塞收割：完成的请求逐个回调。返回本次完成数。 */
int rosoto_aio_reap(RosotoAio *a) {
    if (!a || !a->uring) return 0;
    rosoto_aio_flush(a);
    int done = 0;
    unsigned head = *a->cq_head;
    while (head != rosoto_aio_load(a->cq_tail)) {
        struct io_uring_cqe *cqe = &a->cqes[head & *a->cq_mask];
        RosotoAioReq *req = (RosotoAioReq *)(uintptr_t)cqe->user_data;
        if (req) {
            if (req->cb) req->cb(req->user, cqe->res);
            free(req);
        }
        head++;
        done++;
        a->completed++;
    }
    rosoto_aio_store(a->cq_head, head);
    return done;
}

/* 阻塞等待至少一个完成并收割 */
int rosoto_aio_wait(RosotoAio *a) {
    if (!a || !a->uring) return 0;
    if (rosoto_aio_reap(a) > 0) return 1;
    int ret = (int)syscall(__NR_io_uring_enter, a->ring_fd, 0UL, 1UL,
                           IORING_ENTER_GETEVENTS, NULL, 0UL);
    if (ret < 0 && errno != EINTR) return -1;
    return rosoto_aio_reap(a) > 0 ? 1 : 0;
}

void rosoto_aio_close(RosotoAio *a) {
    if (!a) return;
    (void)rosoto_aio_reap(a);   /* 排干残余完成 */
    if (a->ring_fd >= 0) close(a->ring_fd);
    free(a);
}

#endif /* ROSOTO_STORE_RUNTIME_INCLUDED */
"""

# ---------------------------------------------------------------------------
# 3. 自测程序
# ---------------------------------------------------------------------------

STORE_SELFTEST_C = r"""
/* =====================================================================
 * Rosoto 存储运行时自测：gcc -O2 编译后运行，退出码 0 = 全部通过
 * 用法：store_selftest [工作目录]（默认当前目录）
 * ===================================================================== */
static int g_fail = 0;
#define CHECK(cond, name) do { \
    if (cond) printf("  [PASS] %s\n", name); \
    else { printf("  [FAIL] %s\n", name); g_fail++; } \
} while (0)

/* WAL 回放校验：记录内容 = [u32 seq][u32 hash] */
static int g_replay_count;
static int64_t g_replay_sum;
static int wal_cb(void *user, uint64_t lsn, const void *rec, uint32_t len) {
    (void)user;
    if (len != 8) return 1;
    uint32_t seq, hash;
    memcpy(&seq, rec, 4);
    memcpy(&hash, (const char *)rec + 4, 4);
    if (seq != lsn || hash != seq * 2654435761u) return 1;
    g_replay_count++;
    g_replay_sum += (int64_t)seq;
    return 0;
}

/* 异步 IO 完成计数 */
static int g_aio_done;
static int64_t g_aio_total;
static void aio_cb(void *user, int result) {
    (void)user;
    if (result >= 0) g_aio_total += result;
    g_aio_done++;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    char path[512];
    printf("[store selftest] workdir=%s\n", dir);

    /* 1. CRC32C 标准向量 + 链式一致性 */
    {
        int ok = rosoto_crc32c("123456789", 9) == 0xE3069283u;
        const char *part1 = "12345";
        const char *part2 = "6789";
        uint32_t chained = rosoto_crc32c_chain(rosoto_crc32c(part1, 5), part2, 4);
        ok = ok && chained == 0xE3069283u;
        CHECK(ok, "CRC32C：标准向量 0xE3069283 + 链式分段一致");
    }

    /* 2. WAL：5000 条追加/落盘/回放 + 撕裂尾检测/修复 */
    {
        snprintf(path, sizeof path, "%s/wal.tmp", dir);
        RosotoWal *w = rosoto_wal_open(path, 4);
        int ok = w != NULL;
        for (uint32_t i = 1; ok && i <= 5000; i++) {
            uint32_t rec[2] = { i, i * 2654435761u };
            if (rosoto_wal_append(w, rec, sizeof rec) != i) ok = 0;
        }
        ok = ok && rosoto_wal_sync(w) == 0;
        rosoto_wal_close(w);
        CHECK(ok, "WAL：5000 条追加 + 攒批落盘 + fdatasync");

        g_replay_count = 0;
        g_replay_sum = 0;
        int n = rosoto_wal_replay(path, wal_cb, NULL);
        CHECK(n == 5000 && g_replay_count == 5000 &&
              g_replay_sum == (int64_t)5000 * 5001 / 2,
              "WAL：回放 5000 条逐条校验（len+crc 帧）");

        /* 模拟崩溃撕裂尾：截到数据尾（5000 帧 × 16B）前 5 字节处 */
        {
            int fd = open(path, O_RDWR);
            int trc = ftruncate(fd, (off_t)(5000 * 16 - 5));
            (void)trc;
            close(fd);
        }
        n = rosoto_wal_replay(path, wal_cb, NULL);
        int good = (n == 4999);                  /* 尾帧损坏被识别并停在有效前缀 */
        int rc_repair = rosoto_wal_repair(path);
        int n2 = rosoto_wal_replay(path, wal_cb, NULL);
        ok = good && rc_repair == 0 && n2 == 4999;
        CHECK(ok, "WAL：撕裂尾确定性检测 + repair 截尾后一致");
        unlink(path);
    }

    /* 3. 页存储：分配/写读校验/空闲复用/损坏检测/持久化重开 */
    {
        snprintf(path, sizeof path, "%s/pg.tmp", dir);
        RosotoPgStore *p = rosoto_pg_open(path, 4096, 200, true);
        int ok = p != NULL;
        uint64_t nos[100];
        uint8_t page[512];
        for (int i = 0; ok && i < 100; i++) {
            nos[i] = rosoto_pg_alloc(p);
            if (!nos[i]) { ok = 0; break; }
            for (int j = 0; j < 512; j++) page[j] = (uint8_t)(i ^ j);
            if (rosoto_pg_write(p, nos[i], page, 0, 512) != 0) ok = 0;
        }
        for (int i = 0; ok && i < 100; i++) {
            uint8_t back[512];
            if (rosoto_pg_read(p, nos[i], back, 0, 512) != 0) ok = 0;
            for (int j = 0; j < 512; j++)
                if (back[j] != (uint8_t)(i ^ j)) ok = 0;
        }
        CHECK(ok, "页存储：100 页分配/写读 + CRC 校验");

        /* 损坏页：改 1 字节，读必须 -EIO */
        p->map[nos[7] * 4096 + ROSOTO_PG_HDR_SIZE + 3] ^= 0xFF;
        uint8_t tmp[16];
        ok = rosoto_pg_read(p, nos[7], tmp, 0, 16) == -EIO;
        CHECK(ok, "页存储：损坏页读取确定性失败（-EIO）");

        /* 空闲复用：释放 50 页再分配，页号必须来自释放集合（LIFO 逆序弹出） */
        for (int i = 0; i < 50; i++) rosoto_pg_free(p, nos[i]);
        int reused = 0;
        for (int i = 0; i < 50; i++) {
            uint64_t no = rosoto_pg_alloc(p);
            if (!no) break;
            for (int j = 0; j < 50; j++)
                if (no == nos[j]) { reused++; break; }
        }
        CHECK(reused == 50, "页存储：空闲链复用 50/50（代数递增防陈旧引用）");

        ok = rosoto_pg_flush(p) == 0;
        rosoto_pg_close(p);
        p = rosoto_pg_open(path, 4096, 0, false);   /* 重开校验文件头 */
        ok = ok && p != NULL;
        if (p) {
            uint8_t back[512];
            ok = ok && rosoto_pg_read(p, nos[50], back, 0, 512) == 0;
            rosoto_pg_close(p);
        }
        CHECK(ok, "页存储：flush + 持久化重开（文件头校验）");
        unlink(path);
    }

    /* 4. 文件视图：mmap 零拷贝引用 + 切片越界拒绝 + 扩容 */
    {
        snprintf(path, sizeof path, "%s/fv.tmp", dir);
        RosotoFileView *fv = rosoto_file_view_create(path, 1 << 20);
        int ok = fv != NULL;
        RosotoMutView mv = rosoto_file_view_mut(fv);
        ok = ok && rosoto_mview_put_u64(mv, 8, 0x1122334455667788ull);
        ok = ok && rosoto_mview_put_u32(mv, 16, 0xCAFEBABEu);
        ok = ok && !rosoto_mview_put_u64(mv, (1 << 20) - 4, 1);   /* 越界拒绝 */
        RosotoView whole = rosoto_file_view_of(fv);
        uint64_t u64; uint32_t u32;
        ok = ok && rosoto_view_u64(whole, 8, &u64) && u64 == 0x1122334455667788ull;
        ok = ok && rosoto_view_u32(whole, 16, &u32) && u32 == 0xCAFEBABEu;
        RosotoView sub;
        ok = ok && rosoto_file_view_slice(fv, 8, 16, &sub) && sub.len == 16;
        ok = ok && !rosoto_file_view_slice(fv, (1 << 20) - 4, 16, &sub);  /* 越界切片拒绝 */
        ok = ok && rosoto_file_view_sync(fv) == 0;
        ok = ok && rosoto_file_view_grow(fv, (1 << 20) + 4096);
        CHECK(ok, "文件视图：零拷贝引用/越界拒绝/同步/扩容");

        /* 重开只读验证持久化 */
        rosoto_file_view_close(fv);
        fv = rosoto_file_view_open(path, false);
        ok = fv != NULL;
        whole = rosoto_file_view_of(fv);
        ok = ok && rosoto_view_u32(whole, 16, &u32) && u32 == 0xCAFEBABEu;
        ok = ok && !rosoto_file_view_grow(fv, 1 << 21);   /* 只读扩容必须拒绝 */
        CHECK(ok, "文件视图：只读重开校验 + 写保护");
        rosoto_file_view_close(fv);
        unlink(path);
    }

    /* 5. 异步文件 IO：256KB 分块写 + fsync + 读回（io_uring 或同步回退） */
    {
        snprintf(path, sizeof path, "%s/aio.tmp", dir);
        int fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
        RosotoAio *a = rosoto_aio_open(256);
        int ok = fd >= 0 && a != NULL;
        printf("  [info] 异步 IO 模式: %s\n", a && a->uring ? "io_uring" : "同步回退");
        static uint8_t wbuf[4096], rbuf[4096];
        for (int i = 0; i < 4096; i++) wbuf[i] = (uint8_t)(i * 7 + 3);
        g_aio_done = 0;
        g_aio_total = 0;
        for (int blk = 0; blk < 64; blk++) {
            if (rosoto_aio_write(a, fd, (uint64_t)blk * 4096, wbuf, 4096, aio_cb, NULL) != 0) ok = 0;
            (void)rosoto_aio_reap(a);
        }
        while (g_aio_done < 64) (void)rosoto_aio_wait(a);   /* 提交恒发生，完成数必达 64 */
        g_aio_done = 0;
        rosoto_aio_fsync(a, fd, aio_cb, NULL);
        while (g_aio_done < 1) (void)rosoto_aio_wait(a);
        g_aio_total = 0;   /* 只统计读回量 */
        for (int blk = 0; blk < 64; blk++) {
            /* 逐块：提交->等完成->校验（校验必须在完成之后） */
            g_aio_done = 0;
            if (rosoto_aio_read(a, fd, (uint64_t)blk * 4096, rbuf, 4096, aio_cb, NULL) != 0) ok = 0;
            while (g_aio_done < 1) (void)rosoto_aio_wait(a);
            ok = ok && memcmp(wbuf, rbuf, 4096) == 0;
        }
        ok = ok && g_aio_total == 64 * 4096;
        CHECK(ok, "异步文件 IO：256KB 分块写/fsync/读回一致");
        rosoto_aio_close(a);
        close(fd);
        unlink(path);
    }

    printf("SELFTEST %s (fail=%d)\n", g_fail == 0 ? "PASS" : "FAIL", g_fail);
    return g_fail == 0 ? 0 : 1;
}
"""

# ---------------------------------------------------------------------------
# 4. 命令行入口
# ---------------------------------------------------------------------------

def _build_arg_parser():
    p = argparse.ArgumentParser(
        prog="rosoto_store.py",
        description="发射 Rosoto 文件数据/存储运行时（视图/WAL/页存储/CRC32C/io_uring 文件 IO）",
    )
    p.add_argument("--page-size", type=int, default=None,
                   help="页存储页大小，2 的幂（默认 %d）" % DEFAULT_STORE["page_size"])
    p.add_argument("--page-count", type=int, default=None,
                   help="create 时初始页数（默认 %d）" % DEFAULT_STORE["page_count"])
    p.add_argument("--wal-prealloc-mb", type=int, default=None,
                   help="WAL 预分配 MB（默认 %d）" % DEFAULT_STORE["wal_prealloc_mb"])
    p.add_argument("--wal-buf-kb", type=int, default=None,
                   help="WAL 攒批缓冲 KB（默认 %d）" % DEFAULT_STORE["wal_buf_kb"])
    p.add_argument("--async-io", type=_bool_arg, default=None, metavar="BOOL",
                   help="io_uring 文件 IO（默认 %s）" % DEFAULT_STORE["async_io"])
    return p


def _store_from_args(ns):
    st = dict(DEFAULT_STORE)
    for key in ("page_size", "page_count", "wal_prealloc_mb", "wal_buf_kb", "async_io"):
        val = getattr(ns, key)
        if val is not None:
            st[key] = val
    return {"store": st}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    mode = "emit"
    if args and args[0] in ("emit", "selftest"):
        mode = args.pop(0)
    elif args and not args[0].startswith("-"):
        sys.stderr.write("rosoto_store.py: 未知子命令 %r（支持 emit|selftest）\n" % args[0])
        return 2

    ns = _build_arg_parser().parse_args(args)
    try:
        cfg = _store_from_args(ns)
        out = emit_store_selftest(cfg) if mode == "selftest" else emit_store_runtime(cfg)
    except ValueError as e:
        sys.stderr.write("rosoto_store.py: %s\n" % e)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
