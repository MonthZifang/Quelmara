#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto 内存与引用子系统运行时发射器
====================================

面向 SPEC.md §2「内存模型」与「数据库 / 存储类 / 数据类」场景，发射一段
自包含 C99 运行时（无 GC、无 malloc 热点、缓存友好）：

* **Arena bump 分配器** —— 批量分配、整体释放；帧 arena（游戏帧循环帧末
  一次性回收，O(块数)）；每核独立 arena 无锁（配合 rosoto_mt.py）
* **Slab 定长对象池** —— 数据类/行/节点的固定大小对象，空闲链复用，
  热路径零 malloc；设计为每核一个 slab，天然无锁
* **稳定引用 RosotoRef** —— 8 字节「索引 + 代数」句柄，代替裸指针传递；
  use-after-free 可检测（陈旧代数解析返回 NULL），数据类跨核安全引用
* **零拷贝视图 RosotoView** —— 指针+长度的边界检查窗口，小端编码/解码
  访问器（u8..u64/i64/f32/f64）、切片、查找；文件数据 mmap 后整段引用
* **缓存与大页** —— 缓存行对齐分配、读写预取提示、MADV_HUGEPAGE 大页
  映射（失败自动回退普通页）
* **堆上限记账** —— Rosoto.toml [memory] heap_limit_mb 硬上限，超限分配
  确定性失败（返回 NULL），不静默膨胀

用法::

    python3 tools/rosoto_mem.py emit     [--heap-limit-mb N] [--arena-block-size N]
                                        [--slab-chunk-objs N] [--huge-pages true|false]
    python3 tools/rosoto_mem.py selftest [同上]        # 发射带 main() 的自测程序

库用法::

    from rosoto_mem import emit_mem_runtime, emit_mem_selftest
"""

import argparse
import sys

__all__ = ["emit_mem_runtime", "emit_mem_selftest", "DEFAULT_MEM", "main"]

# ---------------------------------------------------------------------------
# 0. 默认配置（与 Rosoto.toml [memory] 节对齐）
# ---------------------------------------------------------------------------

DEFAULT_MEM = {
    "heap_limit_mb": 512,       # [memory] heap_limit_mb：0 = 不限
    "arena_default": False,     # [memory] arena_default（信息性，默认 arena 关）
    "arena_block_size": 262144,  # arena 块大小（字节）
    "slab_chunk_objs": 256,     # slab 每块对象数
    "ref_table_cap": 65536,     # 稳定引用表初始容量
    "huge_pages": False,        # 大页映射（MADV_HUGEPAGE，失败回退）
}

_INT_RANGES = {
    "heap_limit_mb": (0, 1 << 20),
    "arena_block_size": (4096, 1 << 24),
    "slab_chunk_objs": (16, 1 << 16),
    "ref_table_cap": (16, 1 << 24),
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


def _as_int(v, name):
    lo, hi = _INT_RANGES[name]
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"配置项 {name} 需要整数，得到: {v!r}")
    if not (lo <= n <= hi):
        raise ValueError(f"配置项 {name} 超出范围 [{lo}, {hi}]，得到: {n}")
    return n


def _bool_arg(s):
    """argparse type 回调：单参包装 _as_bool。"""
    return _as_bool(s, "命令行参数")


def _mem_section(config):
    """兼容 `{"memory": {...}}` 与扁平 dict 两种入参。"""
    mem = dict(DEFAULT_MEM)
    if not config:
        return mem
    if not isinstance(config, dict):
        raise ValueError(f"config 需要 dict，得到: {type(config).__name__}")
    src = config.get("memory") if isinstance(config.get("memory"), dict) else config
    for k, v in src.items():
        if k in mem:
            mem[k] = v
    return mem


# ---------------------------------------------------------------------------
# 1. 发射器
# ---------------------------------------------------------------------------

def emit_mem_runtime(config: dict) -> str:
    """返回内存/引用子系统 C99 运行时（不含 main，可与其他运行时拼接）。"""
    mem = _mem_section(config)
    heap_limit_mb = _as_int(mem.get("heap_limit_mb"), "heap_limit_mb")
    arena_block = _as_int(mem.get("arena_block_size"), "arena_block_size")
    slab_chunk = _as_int(mem.get("slab_chunk_objs"), "slab_chunk_objs")
    ref_cap = _as_int(mem.get("ref_table_cap"), "ref_table_cap")
    huge = 1 if _as_bool(mem.get("huge_pages"), "huge_pages") else 0

    defines = f"""\
/* ==== Rosoto 内存运行时编译期配置（由 tools/rosoto_mem.py 注入） ==== */
#ifndef ROSOTO_HEAP_LIMIT_MB
#define ROSOTO_HEAP_LIMIT_MB {heap_limit_mb}   /* [memory] heap_limit_mb：0=不限，超限分配失败 */
#endif
#ifndef ROSOTO_ARENA_BLOCK
#define ROSOTO_ARENA_BLOCK {arena_block}      /* arena 块大小（字节） */
#endif
#ifndef ROSOTO_SLAB_CHUNK_OBJS
#define ROSOTO_SLAB_CHUNK_OBJS {slab_chunk}   /* slab 每块对象数 */
#endif
#ifndef ROSOTO_REFTAB_CAP
#define ROSOTO_REFTAB_CAP {ref_cap}       /* 稳定引用表初始容量 */
#endif
#ifndef ROSOTO_HUGE_PAGES
#define ROSOTO_HUGE_PAGES {huge}           /* 1=尝试大页映射（失败回退普通页） */
#endif
"""
    return defines + MEM_RUNTIME_C


def emit_mem_selftest(config: dict) -> str:
    """返回运行时 + 自测 main() 的完整 C 程序（退出码 0 = 全部通过）。"""
    return emit_mem_runtime(config) + MEM_SELFTEST_C


# ---------------------------------------------------------------------------
# 2. C 运行时
# ---------------------------------------------------------------------------

MEM_RUNTIME_C = r"""
/* =====================================================================
 * Rosoto 内存与引用子系统
 * ---------------------------------------------------------------------
 * 设计目标（数据库 / 存储引擎 / 游戏通用）：
 *   1. 热路径零 malloc：arena 批量分配、slab 定长复用、任务级缓冲回收
 *   2. 缓存友好：64B 缓存行对齐、可预取、无伪共享（统计按核隔离）
 *   3. 引用强：稳定句柄（索引+代数）替代裸指针，use-after-free 可检测；
 *      文件数据用零拷贝视图（指针+长度+边界检查）整体引用，不拷贝
 *   4. 资源可预测：[memory] heap_limit_mb 硬上限，超限分配确定性失败
 *
 * 每连接/对象内存预算（数据库行场景示例，slab obj=128B）：
 *   每对象 128B + 空闲链内嵌指针 8B（复用对象体） => 无额外开销
 *   每 chunk：256 对象 × 128B + 头 32B ≈ 32KB（malloc 一次，长期复用）
 *   引用表：每槽 16B（ptr 8 + gen 4 + next 4），1M 行引用 ≈ 16MB
 * ===================================================================== */
#ifndef ROSOTO_MEM_RUNTIME_INCLUDED
#define ROSOTO_MEM_RUNTIME_INCLUDED

#define _GNU_SOURCE
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/types.h>

/* ---- 0. 缓存行 / 时间 / 预取（与其他运行时共享，幂等） ---- */
#ifndef ROSOTO_CACHELINE
#define ROSOTO_CACHELINE 64
#endif
#ifndef ROSOTO_NOW_NS_DEFINED
#define ROSOTO_NOW_NS_DEFINED
/* 单调时钟（游戏帧计时 / 性能统计共用） */
static uint64_t rosoto_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
#endif
#define rosoto_prefetch_r(p) __builtin_prefetch((const void *)(p), 0, 3)  /* 读预取 */
#define rosoto_prefetch_w(p) __builtin_prefetch((const void *)(p), 1, 3)  /* 写预取 */
#define ROSOTO_ALIGNED(n) __attribute__((aligned(n)))

/* ---- 1. 堆上限记账（[memory] heap_limit_mb 硬上限） ---- */
static uint64_t g_heap_limit;   /* 0 = 不限 */
static ROSOTO_ALIGNED(ROSOTO_CACHELINE) uint64_t g_heap_used;   /* relaxed 原子 */

void rosoto_mem_set_heap_limit_mb(int64_t mb) {
    g_heap_limit = mb > 0 ? (uint64_t)mb * 1024ull * 1024ull : 0;
}
uint64_t rosoto_mem_heap_used(void) {
    return __atomic_load_n(&g_heap_used, __ATOMIC_RELAXED);
}
/* 记账；超出上限返回 false（分配失败，不静默膨胀） */
static bool rosoto_heap_charge(uint64_t n) {
    if (g_heap_limit == 0) {
        __atomic_add_fetch(&g_heap_used, n, __ATOMIC_RELAXED);
        return true;
    }
    uint64_t cur = __atomic_load_n(&g_heap_used, __ATOMIC_RELAXED);
    for (;;) {
        if (cur + n > g_heap_limit) return false;
        if (__atomic_compare_exchange_n(&g_heap_used, &cur, cur + n,
                                        false, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
            return true;
    }
}
static void rosoto_heap_discharge(uint64_t n) {
    __atomic_sub_fetch(&g_heap_used, n, __ATOMIC_RELAXED);
}

/* ---- 2. 对齐分配 / 大页映射 ---- */
/* 缓存行对齐分配（避免伪共享） */
void *rosoto_aligned_alloc(size_t size, size_t align) {
    if (align < sizeof(void *)) align = sizeof(void *);
    if ((align & (align - 1)) != 0) return NULL;        /* align 必须 2 的幂 */
    if (size == 0) size = align;
    size = (size + align - 1) & ~(align - 1);
    if (!rosoto_heap_charge(size)) return NULL;
    void *p = NULL;
    if (posix_memalign(&p, align, size) != 0) {
        rosoto_heap_discharge(size);
        return NULL;
    }
    return p;
}
void rosoto_aligned_free(void *p, size_t size) {
    if (!p) return;
    size_t align = sizeof(void *);
    size = (size + align - 1) & ~(align - 1);
    free(p);
    rosoto_heap_discharge(size);
}

/* 大页映射（MADV_HUGEPAGE 提示；内核不支持/碎片化时自动回退普通页，
 * 不影响正确性，只影响 TLB 压力）。size 向上取整到页。 */
void *rosoto_huge_alloc(size_t size) {
    long ps = sysconf(_SC_PAGESIZE);
    size_t page = ps > 0 ? (size_t)ps : 4096;
    size_t n = (size + page - 1) & ~(page - 1);
    if (n == 0) n = page;
    if (!rosoto_heap_charge(n)) return NULL;
    void *p = mmap(NULL, n, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        rosoto_heap_discharge(n);
        return NULL;
    }
#if defined(MADV_HUGEPAGE) && ROSOTO_HUGE_PAGES
    (void)madvise(p, n, MADV_HUGEPAGE);   /* 失败忽略：回退普通页 */
#endif
    return p;
}
void rosoto_huge_free(void *p, size_t size) {
    if (!p) return;
    long ps = sysconf(_SC_PAGESIZE);
    size_t page = ps > 0 ? (size_t)ps : 4096;
    size_t n = (size + page - 1) & ~(page - 1);
    if (n == 0) n = page;
    munmap(p, n);
    rosoto_heap_discharge(n);
}

/* ---- 3. Arena：块 bump 分配器（批量分配、整体释放） ---- */
typedef struct RosotoArenaBlock {
    struct RosotoArenaBlock *next;
    size_t cap;    /* 本块数据容量 */
    size_t used;   /* 已用字节 */
    /* 数据区紧跟结构体（柔性布局） */
} RosotoArenaBlock;

typedef struct RosotoArena {
    RosotoArenaBlock *head;   /* 当前分配块（满则换新块） */
    RosotoArenaBlock *all;    /* 全部块链（reset/destroy 用） */
    size_t block_size;        /* 块大小 */
    size_t total_reserved;    /* 累计申请字节（预算监控） */
    size_t total_used;        /* 累计实际分配字节 */
    uint64_t allocs;
} RosotoArena;

void rosoto_arena_init(RosotoArena *a, size_t block_size) {
    memset(a, 0, sizeof *a);
    a->block_size = block_size ? block_size : (size_t)ROSOTO_ARENA_BLOCK;
}
static RosotoArenaBlock *rosoto_arena_grow(RosotoArena *a, size_t need) {
    size_t cap = a->block_size;
    if (need > cap) cap = need;   /* 超大对象独占块 */
    size_t total = sizeof(RosotoArenaBlock) + cap;
    if (!rosoto_heap_charge(total)) return NULL;
    RosotoArenaBlock *b = (RosotoArenaBlock *)malloc(sizeof(RosotoArenaBlock) + cap);
    if (!b) {
        rosoto_heap_discharge(total);
        return NULL;
    }
    b->cap = cap;
    b->used = 0;
    b->next = a->all;
    a->all = b;
    a->head = b;
    a->total_reserved += total;
    return b;
}
/* bump 分配：对齐后取当前块；不足则换新块。O(1)，无逐对象 free。
 * 对齐按【绝对地址】计算（块头大小不是对齐数倍数时，块内偏移需补斜） */
void *rosoto_arena_alloc(RosotoArena *a, size_t size, size_t align) {
    if (size == 0) size = 1;
    if (align == 0) align = 16;
    if ((align & (align - 1)) != 0) return NULL;
    RosotoArenaBlock *b = a->head;
    for (;;) {
        if (b) {
            uintptr_t base = (uintptr_t)(b + 1);
            size_t off = (size_t)(((base + b->used + align - 1) & ~(uintptr_t)(align - 1)) - base);
            if (off + size <= b->cap) {
                void *p = (char *)(b + 1) + off;
                b->used = off + size;
                a->total_used += size;
                a->allocs++;
                return p;
            }
        }
        /* 不足：换新块（预留对齐斜量，保证首分配就能对齐） */
        b = rosoto_arena_grow(a, size + align);
        if (!b) return NULL;
    }
}
/* 整体重置：保留块链，全部 used=0 —— 帧末/阶段末 O(块数) 回收 */
void rosoto_arena_reset(RosotoArena *a) {
    for (RosotoArenaBlock *b = a->all; b; b = b->next) b->used = 0;
    a->head = a->all;
}
void rosoto_arena_destroy(RosotoArena *a) {
    RosotoArenaBlock *b = a->all;
    while (b) {
        RosotoArenaBlock *n = b->next;
        size_t total = sizeof(RosotoArenaBlock) + b->cap;
        free(b);
        rosoto_heap_discharge(total);
        b = n;
    }
    memset(a, 0, sizeof *a);
}

/* ---- 4. 帧 Arena（游戏帧循环：本帧分配、帧末整体释放） ---- */
static RosotoArena g_frame_arena;
static int g_frame_arena_ready;

void rosoto_frame_arena_begin(void) {
    if (!g_frame_arena_ready) {
        rosoto_arena_init(&g_frame_arena, (size_t)ROSOTO_ARENA_BLOCK);
        g_frame_arena_ready = 1;
    }
    rosoto_arena_reset(&g_frame_arena);   /* 开帧即回收上一帧 */
}
void *rosoto_frame_alloc(size_t size, size_t align) {
    return rosoto_arena_alloc(&g_frame_arena, size, align);
}
void rosoto_frame_arena_end(void) {
    rosoto_arena_reset(&g_frame_arena);   /* 帧末整体释放（块保留复用） */
}

/* ---- 5. Slab：定长对象池（数据类/行/节点；热路径零 malloc） ---- */
typedef struct RosotoSlabChunk {
    struct RosotoSlabChunk *next;
    /* 对象区紧跟结构体 */
} RosotoSlabChunk;

typedef struct RosotoSlab {
    uint32_t obj_size;      /* 对齐后的对象大小（>= sizeof(void*)） */
    uint32_t objs_per_chunk;
    RosotoSlabChunk *chunks; /* chunk 链（destroy 用） */
    void *free_list;         /* 空闲对象单链（next 内嵌在对象体） */
    uint64_t live;           /* 在用对象数 */
    uint64_t allocs, frees;
    uint32_t nchunks;
} RosotoSlab;

void rosoto_slab_init(RosotoSlab *s, uint32_t obj_size, uint32_t objs_per_chunk) {
    memset(s, 0, sizeof *s);
    uint32_t sz = (obj_size + 15u) & ~15u;
    if (sz < (uint32_t)sizeof(void *)) sz = (uint32_t)sizeof(void *);
    s->obj_size = sz;
    s->objs_per_chunk = objs_per_chunk ? objs_per_chunk : ROSOTO_SLAB_CHUNK_OBJS;
}
static bool rosoto_slab_new_chunk(RosotoSlab *s) {
    size_t data = (size_t)s->obj_size * s->objs_per_chunk;
    size_t total = sizeof(RosotoSlabChunk) + data;
    if (!rosoto_heap_charge(total)) return false;
    RosotoSlabChunk *c = (RosotoSlabChunk *)malloc(total);
    if (!c) {
        rosoto_heap_discharge(total);
        return false;
    }
    c->next = s->chunks;
    s->chunks = c;
    s->nchunks++;
    /* 新块所有对象挂入空闲链 */
    char *base = (char *)(c + 1);
    for (uint32_t i = 0; i < s->objs_per_chunk; i++) {
        void *obj = base + (size_t)i * s->obj_size;
        *(void **)obj = s->free_list;
        s->free_list = obj;
    }
    return true;
}
void *rosoto_slab_alloc(RosotoSlab *s) {
    if (!s->free_list && !rosoto_slab_new_chunk(s)) return NULL;
    void *obj = s->free_list;
    s->free_list = *(void **)obj;
    s->live++;
    s->allocs++;
    return obj;
}
void rosoto_slab_free(RosotoSlab *s, void *obj) {
    if (!obj) return;
    *(void **)obj = s->free_list;
    s->free_list = obj;
    if (s->live) s->live--;
    s->frees++;
}
void rosoto_slab_destroy(RosotoSlab *s) {
    RosotoSlabChunk *c = s->chunks;
    size_t total = sizeof(RosotoSlabChunk) + (size_t)s->obj_size * s->objs_per_chunk;
    while (c) {
        RosotoSlabChunk *n = c->next;
        free(c);
        rosoto_heap_discharge(total);
        c = n;
    }
    memset(s, 0, sizeof *s);
}

/* ---- 6. 稳定引用 RosotoRef（数据类/行的强引用，8 字节） ---- */
/* 语义：引用 = (槽位索引, 代数)。对象删除后代数递增，旧引用解析必得 NULL，
 * use-after-free 从「未定义行为」变成「确定性失败」。跨核传递只搬 8 字节。 */
#ifndef ROSOTO_REF_DEFINED
#define ROSOTO_REF_DEFINED
typedef struct RosotoRef { uint32_t idx; uint32_t gen; } RosotoRef;
#define ROSOTO_REF_NULL ((RosotoRef){ 0xFFFFFFFFu, 0 })
#endif

typedef struct RosotoRefSlot {
    void *ptr;
    uint32_t gen;       /* 0 = 未使用过的空槽 */
    uint32_t next_free;
} RosotoRefSlot;

typedef struct RosotoRefTable {
    RosotoRefSlot *slots;
    uint32_t cap;
    uint32_t free_head;   /* 空闲槽链头；0xFFFFFFFF = 无 */
    uint32_t live;
} RosotoRefTable;

int rosoto_reftab_init(RosotoRefTable *t, uint32_t cap) {
    if (cap < 16) cap = 16;
    size_t bytes = (size_t)cap * sizeof(RosotoRefSlot);
    if (!rosoto_heap_charge(bytes)) return -1;
    t->slots = (RosotoRefSlot *)calloc(cap, sizeof(RosotoRefSlot));
    if (!t->slots) {
        rosoto_heap_discharge(bytes);
        return -1;
    }
    t->cap = cap;
    t->live = 0;
    t->free_head = 0;
    for (uint32_t i = 0; i < cap - 1; i++) t->slots[i].next_free = i + 1;
    t->slots[cap - 1].next_free = 0xFFFFFFFFu;
    return 0;
}
static bool rosoto_reftab_grow(RosotoRefTable *t) {
    uint32_t ncap = t->cap * 2;
    size_t bytes = (size_t)ncap * sizeof(RosotoRefSlot);
    if (!rosoto_heap_charge(bytes)) return false;
    RosotoRefSlot *ns = (RosotoRefSlot *)realloc(t->slots, bytes);
    if (!ns) {
        rosoto_heap_discharge(bytes);
        return false;
    }
    /* 差额记账（realloc 已吃掉旧块） */
    rosoto_heap_discharge((size_t)t->cap * sizeof(RosotoRefSlot));
    t->slots = ns;
    for (uint32_t i = t->cap; i < ncap - 1; i++) {
        t->slots[i].ptr = NULL;
        t->slots[i].gen = 0;
        t->slots[i].next_free = i + 1;
    }
    t->slots[ncap - 1].ptr = NULL;
    t->slots[ncap - 1].gen = 0;
    t->slots[ncap - 1].next_free = 0xFFFFFFFFu;
    t->free_head = t->cap;
    t->cap = ncap;
    return true;
}
RosotoRef rosoto_reftab_put(RosotoRefTable *t, void *obj) {
    if (t->free_head == 0xFFFFFFFFu && !rosoto_reftab_grow(t)) return ROSOTO_REF_NULL;
    uint32_t idx = t->free_head;
    RosotoRefSlot *s = &t->slots[idx];
    t->free_head = s->next_free;
    s->ptr = obj;
    if (s->gen == 0) s->gen = 1;   /* 代数 0 保留给「从未使用」 */
    t->live++;
    RosotoRef r = { idx, s->gen };
    return r;
}
void *rosoto_reftab_get(RosotoRefTable *t, RosotoRef r) {
    if (r.idx >= t->cap) return NULL;
    RosotoRefSlot *s = &t->slots[r.idx];
    if (s->gen != r.gen || s->ptr == NULL) return NULL;   /* 陈旧/无效引用 */
    return s->ptr;
}
void rosoto_reftab_del(RosotoRefTable *t, RosotoRef r) {
    if (r.idx >= t->cap) return;
    RosotoRefSlot *s = &t->slots[r.idx];
    if (s->gen != r.gen || s->ptr == NULL) return;
    s->ptr = NULL;
    s->gen++;                       /* 旧引用从此解析失败 */
    if (s->gen == 0) s->gen = 1;
    s->next_free = t->free_head;
    t->free_head = r.idx;
    if (t->live) t->live--;
}
void rosoto_reftab_destroy(RosotoRefTable *t) {
    if (t->slots) {
        rosoto_heap_discharge((size_t)t->cap * sizeof(RosotoRefSlot));
        free(t->slots);
    }
    memset(t, 0, sizeof *t);
}

/* ---- 7. 零拷贝视图 RosotoView（文件/内存数据的强引用） ---- */
/* 语义：(指针, 长度) 的只读窗口，所有访问器边界检查 —— 越界返回 false，
 * 而不是未定义行为。文件 mmap 后整段作为视图传递，数据零拷贝。
 * 编码统一小端（与 x86/ARM 原生一致；大端平台由访问器处理）。 */
#ifndef ROSOTO_VIEW_DEFINED
#define ROSOTO_VIEW_DEFINED
typedef struct RosotoView { const uint8_t *ptr; size_t len; } RosotoView;
typedef struct RosotoMutView { uint8_t *ptr; size_t len; } RosotoMutView;
#endif

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
/* 边界检查切片：越界返回 false 且 *out 为空视图 */
bool rosoto_view_slice(RosotoView v, size_t off, size_t n, RosotoView *out) {
    if (out) {
        out->ptr = NULL;
        out->len = 0;
    }
    if (off > v.len || n > v.len - off) return false;
    if (out) {
        out->ptr = v.ptr + off;
        out->len = n;
    }
    return true;
}

/* ---- 小端读取（越界 false） ---- */
bool rosoto_view_u8(RosotoView v, size_t off, uint8_t *out) {
    if (off + 1 > v.len) return false;
    *out = v.ptr[off];
    return true;
}
bool rosoto_view_u16(RosotoView v, size_t off, uint16_t *out) {
    if (off + 2 > v.len) return false;
    *out = (uint16_t)(v.ptr[off] | ((uint16_t)v.ptr[off + 1] << 8));
    return true;
}
bool rosoto_view_u32(RosotoView v, size_t off, uint32_t *out) {
    if (off + 4 > v.len) return false;
    *out = (uint32_t)v.ptr[off] | ((uint32_t)v.ptr[off + 1] << 8) |
           ((uint32_t)v.ptr[off + 2] << 16) | ((uint32_t)v.ptr[off + 3] << 24);
    return true;
}
bool rosoto_view_u64(RosotoView v, size_t off, uint64_t *out);
bool rosoto_view_i64(RosotoView v, size_t off, int64_t *out);
bool rosoto_view_f32(RosotoView v, size_t off, float *out);
bool rosoto_view_f64(RosotoView v, size_t off, double *out);

/* ---- 小端写入（越界 false） ---- */
bool rosoto_mview_put_u8(RosotoMutView v, size_t off, uint8_t x);
bool rosoto_mview_put_u16(RosotoMutView v, size_t off, uint16_t x);
bool rosoto_mview_put_u32(RosotoMutView v, size_t off, uint32_t x);
bool rosoto_mview_put_u64(RosotoMutView v, size_t off, uint64_t x);
bool rosoto_mview_put_i64(RosotoMutView v, size_t off, int64_t x);
bool rosoto_mview_put_f32(RosotoMutView v, size_t off, float x);
bool rosoto_mview_put_f64(RosotoMutView v, size_t off, double x);

/* 字节查找（记录扫描）：返回首次出现偏移，未找到返回 SIZE_MAX */
size_t rosoto_view_find(RosotoView v, size_t from, const void *needle, size_t n) {
    if (n == 0 || v.len < n || from > v.len - n) return (size_t)-1;
    const uint8_t *p = (const uint8_t *)needle;
    for (size_t i = from; i + n <= v.len; i++) {
        if (memcmp(v.ptr + i, p, n) == 0) return i;
    }
    return (size_t)-1;
}
bool rosoto_view_eq(RosotoView a, RosotoView b) {
    return a.len == b.len && (a.len == 0 || memcmp(a.ptr, b.ptr, a.len) == 0);
}
bool rosoto_view_copy(RosotoMutView dst, size_t off, RosotoView src) {
    if (off > dst.len || src.len > dst.len - off) return false;
    if (src.len) memcpy(dst.ptr + off, src.ptr, src.len);
    return true;
}

/* ---- 8. 随机数（哈希/采样用，xorshift64*，无锁） ---- */
uint64_t rosoto_random_u64(uint64_t *state) {
    uint64_t x = *state;
    x ^= x >> 12;
    x ^= x << 25;
    x ^= x >> 27;
    *state = x ? x : 0x9E3779B97F4A7C15ull;
    return *state * 0x2545F4914F6CDD1Dull;
}

#endif /* ROSOTO_MEM_RUNTIME_INCLUDED */
"""

# 小端读写实现放在独立段（修掉前向声明占位）
MEM_RUNTIME_C += r"""
/* ---- 7b. 视图访问器实现（小端编解码） ---- */
#ifndef ROSOTO_MEM_VIEW_IMPL
#define ROSOTO_MEM_VIEW_IMPL
bool rosoto_view_u64(RosotoView v, size_t off, uint64_t *out) {
    uint32_t lo, hi;
    if (!rosoto_view_u32(v, off, &lo) || !rosoto_view_u32(v, off + 4, &hi)) return false;
    *out = (uint64_t)lo | ((uint64_t)hi << 32);
    return true;
}
bool rosoto_view_i64(RosotoView v, size_t off, int64_t *out) {
    uint64_t u;
    if (!rosoto_view_u64(v, off, &u)) return false;
    *out = (int64_t)u;
    return true;
}
bool rosoto_view_f32(RosotoView v, size_t off, float *out) {
    uint32_t u;
    if (!rosoto_view_u32(v, off, &u)) return false;
    memcpy(out, &u, 4);
    return true;
}
bool rosoto_view_f64(RosotoView v, size_t off, double *out) {
    uint64_t u;
    if (!rosoto_view_u64(v, off, &u)) return false;
    memcpy(out, &u, 8);
    return true;
}
bool rosoto_mview_put_u8(RosotoMutView v, size_t off, uint8_t x) {
    if (off + 1 > v.len) return false;
    v.ptr[off] = x;
    return true;
}
bool rosoto_mview_put_u16(RosotoMutView v, size_t off, uint16_t x) {
    if (off + 2 > v.len) return false;
    v.ptr[off] = (uint8_t)x;
    v.ptr[off + 1] = (uint8_t)(x >> 8);
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
bool rosoto_mview_put_i64(RosotoMutView v, size_t off, int64_t x) {
    return rosoto_mview_put_u64(v, off, (uint64_t)x);
}
bool rosoto_mview_put_f32(RosotoMutView v, size_t off, float x) {
    uint32_t u;
    memcpy(&u, &x, 4);
    return rosoto_mview_put_u32(v, off, u);
}
bool rosoto_mview_put_f64(RosotoMutView v, size_t off, double x) {
    uint64_t u;
    memcpy(&u, &x, 8);
    return rosoto_mview_put_u64(v, off, u);
}
#endif /* ROSOTO_MEM_VIEW_IMPL */
"""

# ---------------------------------------------------------------------------
# 3. 自测程序
# ---------------------------------------------------------------------------

MEM_SELFTEST_C = r"""
/* =====================================================================
 * Rosoto 内存运行时自测：gcc -O2 编译后运行，退出码 0 = 全部通过
 * ===================================================================== */
static int g_fail = 0;
#define CHECK(cond, name) do { \
    if (cond) printf("  [PASS] %s\n", name); \
    else { printf("  [FAIL] %s\n", name); g_fail++; } \
} while (0)

int main(void) {
    printf("[mem selftest]\n");
    rosoto_mem_set_heap_limit_mb(256);

    /* 1. Arena：变长批量分配 + 内容校验 + reset 后块复用 */
    {
        RosotoArena a;
        rosoto_arena_init(&a, 64 * 1024);
        int ok = 1;
        for (int i = 0; i < 100000; i++) {
            size_t sz = (size_t)(i % 300) + 1;
            char *p = (char *)rosoto_arena_alloc(&a, sz, 16);
            if (!p || ((uintptr_t)p & 15) != 0) { ok = 0; break; }
            memset(p, i & 0xFF, sz);
        }
        CHECK(ok, "arena 10 万次变长分配（16B 对齐）");
        size_t chunks_before = 0;
        for (RosotoArenaBlock *b = a.all; b; b = b->next) chunks_before++;
        rosoto_arena_reset(&a);
        size_t chunks_after = 0;
        for (RosotoArenaBlock *b = a.all; b; b = b->next) chunks_after++;
        CHECK(chunks_before == chunks_after && a.total_used > 0,
              "arena reset 整体回收且块复用（无逐对象 free）");
        rosoto_arena_destroy(&a);
    }

    /* 2. 帧 arena：begin/end 循环，分配稳定复用 */
    {
        int ok = 1;
        for (int frame = 0; frame < 1000; frame++) {
            rosoto_frame_arena_begin();
            for (int i = 0; i < 100; i++) {
                void *p = rosoto_frame_alloc(64, 64);
                if (!p || ((uintptr_t)p & 63) != 0) ok = 0;
            }
            rosoto_frame_arena_end();
        }
        CHECK(ok, "帧 arena 1000 帧分配/整体释放（64B 对齐）");
        rosoto_arena_destroy(&g_frame_arena);
        g_frame_arena_ready = 0;
    }

    /* 3. Slab：分配-释放-复用，对象不重复、无泄漏 */
    {
        RosotoSlab s;
        rosoto_slab_init(&s, 128, 256);
        void *objs[10000];
        int ok = 1;
        uint64_t t0 = rosoto_now_ns();
        for (int i = 0; i < 10000; i++) {
            objs[i] = rosoto_slab_alloc(&s);
            if (!objs[i]) { ok = 0; break; }
            memset(objs[i], i & 0xFF, 128);
        }
        for (int i = 0; i < 10000; i += 2) rosoto_slab_free(&s, objs[i]);
        for (int i = 0; i < 5000; i++) {
            void *p = rosoto_slab_alloc(&s);   /* 应复用刚释放的 */
            if (!p) { ok = 0; break; }
        }
        uint64_t dt = rosoto_now_ns() - t0;   /* 吞吐仅供参考，不作为断言 */
        CHECK(ok && s.live == 10000, "slab 1 万对象分配/释放/复用（热路径零 malloc）");
        printf("  [info] slab 吞吐: %.1f M ops/s\n",
               dt ? 20000.0 / (double)dt * 1000.0 : 0.0);
        rosoto_slab_destroy(&s);
    }

    /* 4. 稳定引用：删除后代数递增，陈旧引用解析必须失败 */
    {
        RosotoRefTable t;
        int ok = rosoto_reftab_init(&t, 64) == 0;
        int a = 1, b = 2;
        RosotoRef ra = rosoto_reftab_put(&t, &a);
        RosotoRef rb = rosoto_reftab_put(&t, &b);
        ok = ok && rosoto_reftab_get(&t, ra) == &a && rosoto_reftab_get(&t, rb) == &b;
        rosoto_reftab_del(&t, ra);
        ok = ok && rosoto_reftab_get(&t, ra) == NULL;    /* 陈旧引用 → NULL */
        RosotoRef rc = rosoto_reftab_put(&t, &b);        /* 槽位复用，代数已变 */
        ok = ok && rc.idx == ra.idx && rosoto_reftab_get(&t, ra) == NULL;
        ok = ok && rosoto_reftab_get(&t, rc) == &b;
        CHECK(ok, "稳定引用：use-after-free 确定性失败（索引+代数）");
        rosoto_reftab_destroy(&t);
    }

    /* 5. 零拷贝视图：小端编解码 + 越界拒绝 + 切片 + 查找 */
    {
        uint8_t buf[64];
        RosotoMutView mv = rosoto_mview(buf, sizeof buf);
        int ok = rosoto_mview_put_u32(mv, 0, 0xDEADBEEFu);
        ok = ok && rosoto_mview_put_u64(mv, 4, 0x0123456789ABCDEFull);
        ok = ok && rosoto_mview_put_f64(mv, 12, 3.141592653589793);
        ok = ok && !rosoto_mview_put_u64(mv, 60, 1);     /* 越界必须拒绝 */
        RosotoView v = rosoto_view(buf, sizeof buf);
        uint32_t u32; uint64_t u64; double f64;
        ok = ok && rosoto_view_u32(v, 0, &u32) && u32 == 0xDEADBEEFu;
        ok = ok && rosoto_view_u64(v, 4, &u64) && u64 == 0x0123456789ABCDEFull;
        ok = ok && rosoto_view_f64(v, 12, &f64) && f64 == 3.141592653589793;
        ok = ok && !rosoto_view_u64(v, 60, &u64);        /* 越界必须拒绝 */
        RosotoView sub;
        ok = ok && rosoto_view_slice(v, 4, 8, &sub) && sub.len == 8;
        ok = ok && !rosoto_view_slice(v, 4, 61, &sub);   /* 越界切片拒绝 */
        const char pat[] = "\xEF\xBE\xAD\xDE";   /* 0xDEADBEEF 的小端字节序 */
        size_t pos = rosoto_view_find(v, 0, pat, 4);
        ok = ok && pos == 0;                             /* 小端字节序 = DEADBEEF 反排 */
        CHECK(ok, "零拷贝视图：LE 编解码/越界拒绝/切片/查找");
    }

    /* 6. 大页/对齐分配 + 堆上限 */
    {
        void *p = rosoto_huge_alloc(4 * 1024 * 1024);
        int ok = p != NULL;
        if (p) {
            memset(p, 0xAB, 4 * 1024 * 1024);
            rosoto_huge_free(p, 4 * 1024 * 1024);
        }
        CHECK(ok, "大页映射（MADV_HUGEPAGE，失败回退普通页）");

        rosoto_mem_set_heap_limit_mb(1);
        void *big = rosoto_aligned_alloc(2 * 1024 * 1024, 64);
        ok = big == NULL;                                /* 超限确定性失败 */
        if (big) rosoto_aligned_free(big, 2 * 1024 * 1024);
        CHECK(ok, "堆上限：超 heap_limit_mb 分配确定性失败");
        rosoto_mem_set_heap_limit_mb(256);
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
        prog="rosoto_mem.py",
        description="发射 Rosoto 内存/引用子系统 C 运行时（arena/slab/稳定引用/零拷贝视图）",
    )
    p.add_argument("--heap-limit-mb", type=int, default=None,
                   help="堆上限 MB，0=不限（默认 %d）" % DEFAULT_MEM["heap_limit_mb"])
    p.add_argument("--arena-block-size", type=int, default=None,
                   help="arena 块大小（默认 %d）" % DEFAULT_MEM["arena_block_size"])
    p.add_argument("--slab-chunk-objs", type=int, default=None,
                   help="slab 每块对象数（默认 %d）" % DEFAULT_MEM["slab_chunk_objs"])
    p.add_argument("--ref-table-cap", type=int, default=None,
                   help="稳定引用表初始容量（默认 %d）" % DEFAULT_MEM["ref_table_cap"])
    p.add_argument("--huge-pages", type=_bool_arg, default=None, metavar="BOOL",
                   help="启用大页提示（默认 %s）" % DEFAULT_MEM["huge_pages"])
    return p


def _mem_from_args(ns):
    mem = dict(DEFAULT_MEM)
    for key in ("heap_limit_mb", "arena_block_size", "slab_chunk_objs",
                "ref_table_cap", "huge_pages"):
        val = getattr(ns, key)
        if val is not None:
            mem[key] = val
    return {"memory": mem}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    mode = "emit"
    if args and args[0] in ("emit", "selftest"):
        mode = args.pop(0)
    elif args and not args[0].startswith("-"):
        sys.stderr.write("rosoto_mem.py: 未知子命令 %r（支持 emit|selftest）\n" % args[0])
        return 2

    ns = _build_arg_parser().parse_args(args)
    try:
        cfg = _mem_from_args(ns)
        out = emit_mem_selftest(cfg) if mode == "selftest" else emit_mem_runtime(cfg)
    except ValueError as e:
        sys.stderr.write("rosoto_mem.py: %s\n" % e)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
