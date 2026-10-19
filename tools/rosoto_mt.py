#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto 多核任务运行时发射器（work-stealing 调度器）
====================================================

对应 SPEC.md §4「多核模型（默认开启）」：**并行是默认行为，单核是显式选择**。
发射一段自包含 C99 运行时（pthread，无第三方依赖）：

* **work-stealing 任务池** —— 每 worker 本地任务队列（LIFO 亲和），
  空闲时随机窃取他核队列尾；热路径零 malloc（线程本地任务缓存）
* **spawn / JoinHandle** —— 显式任务并行，`rosoto_join_wait` 收敛
* **parfor 语义** —— `rosoto_pool_parallel_for`：静态分块（缓存友好）+
  可窃取任务兜底（负载均衡）；第一块调用者内联执行，省一次调度
* **MPMC channel** —— 有界环形队列，任务流水线 / DB 流水线通信用
* **帧屏障** —— `rosoto_pool_wait_idle`：游戏帧循环 spawn 完帧内任务后
  一并等待，帧末确定性收敛
* **单核确定性降级** —— workers=1 或 Rosoto.toml `[core] multicore=false`
  时 spawn 即内联执行、parallel_for 串行，语义不变（SPEC §4 规则 2）
* **绑核 / 配额** —— affinity=none|compact|scatter|[0,1,2]；容器场景自动
  识别 cgroup v1/v2 CPU 配额并收敛线程数（SPEC §4 规则 4）

用法::

    python3 tools/rosoto_mt.py emit     [--threads N] [--affinity none|compact|scatter|[0,1,2]]
                                        [--grain N] [--multicore true|false]
    python3 tools/rosoto_mt.py selftest [同上]     # 发射带 main() 的自测程序

库用法::

    from rosoto_mt import emit_mt_runtime, emit_mt_selftest
"""

import argparse
import re
import sys

__all__ = ["emit_mt_runtime", "emit_mt_selftest", "DEFAULT_CORE", "main"]

# ---------------------------------------------------------------------------
# 0. 默认配置（与 Rosoto.toml [core] 节对齐：多核默认开、单核需显式声明）
# ---------------------------------------------------------------------------

DEFAULT_CORE = {
    "multicore": True,      # [core] multicore：false = 显式单核（确定性串行）
    "threads": 0,           # [core] threads：0 = 自动（物理核数/容器配额）
    "affinity": "none",     # [core] affinity: none|compact|scatter|[0,1,2]
    "preempt": True,        # [core] preempt：安全点抢占（信息性开关）
    "grain": 4096,          # parfor 默认分块粒度（每任务迭代数）
}

AFFINITY_NONE, AFFINITY_COMPACT, AFFINITY_SCATTER, AFFINITY_LIST = 0, 1, 2, 3


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


def _core_section(config):
    """兼容 `{"core": {...}}` 与扁平 dict 两种入参。"""
    core = dict(DEFAULT_CORE)
    if not config:
        return core
    if not isinstance(config, dict):
        raise ValueError(f"config 需要 dict，得到: {type(config).__name__}")
    src = config.get("core") if isinstance(config.get("core"), dict) else config
    for k, v in src.items():
        if k in core:
            core[k] = v
    return core


def _parse_affinity(spec):
    """affinity: none|compact|scatter 或 CPU 列表 [0,1,2] / 0,1,2。返回 (mode, [cpus])。"""
    if isinstance(spec, (list, tuple)):
        cpus = [int(x) for x in spec]
        if not cpus:
            raise ValueError("affinity CPU 列表为空")
        return AFFINITY_LIST, cpus
    s = str(spec).strip().lower()
    if s in ("none", ""):
        return AFFINITY_NONE, []
    if s == "compact":
        return AFFINITY_COMPACT, []
    if s == "scatter":
        return AFFINITY_SCATTER, []
    m = re.fullmatch(r"\[?\s*([\d+\s*,\s*]*)\]?", s)
    if m:
        cpus = [int(x) for x in re.split(r"\s*,\s*", m.group(1).strip()) if x != ""]
        if cpus:
            return AFFINITY_LIST, cpus
    raise ValueError(f"affinity 需为 none|compact|scatter|[0,1,2]，得到: {spec!r}")


# ---------------------------------------------------------------------------
# 1. 发射器
# ---------------------------------------------------------------------------

def emit_mt_runtime(config: dict) -> str:
    """返回多核任务运行时 C99 源码（不含 main，可与其他运行时拼接）。"""
    core = _core_section(config)
    threads = int(core.get("threads", 0))
    if threads < 0 or threads > 4096:
        raise ValueError(f"threads 超出范围 [0, 4096]，得到: {threads}")
    grain = int(core.get("grain", 4096))
    if grain < 1 or grain > (1 << 24):
        raise ValueError(f"grain 超出范围 [1, 16777216]，得到: {grain}")
    multicore = _as_bool(core.get("multicore"), "multicore")
    preempt = _as_bool(core.get("preempt"), "preempt")
    mode, cpus = _parse_affinity(core.get("affinity", "none"))
    cpu_list = ", ".join(str(c) for c in cpus) if cpus else ""
    if mode == AFFINITY_LIST and not cpu_list:
        raise ValueError("affinity 列表模式需要至少一个 CPU")
    ncpu_list = len(cpus)

    # multicore=false → workers 强制 1（SPEC §4：单核必须显式声明）
    workers_default = threads if multicore else 1

    defines = f"""\
/* ==== Rosoto 多核运行时编译期配置（由 tools/rosoto_mt.py 注入） ==== */
#ifndef ROSOTO_WORKERS
#define ROSOTO_WORKERS {workers_default}  /* [core] threads（0=自动；multicore=false 时为 1=显式单核） */
#endif
#ifndef ROSOTO_AFFINITY_MODE
#define ROSOTO_AFFINITY_MODE {mode}  /* [core] affinity: 0=none 1=compact 2=scatter 3=显式列表 */
#endif
#ifndef ROSOTO_PARFOR_GRAIN
#define ROSOTO_PARFOR_GRAIN {grain}  /* parfor 默认分块粒度 */
#endif
#ifndef ROSOTO_PREEMPT
#define ROSOTO_PREEMPT {1 if preempt else 0}  /* [core] preempt：安全点抢占（信息性） */
#endif
#define ROSOTO_AFFINITY_LIST_N {ncpu_list}
static const int rosoto_affinity_cpus[] __attribute__((unused)) = {{ {cpu_list if cpu_list else "0"} }};
"""
    return defines + MT_RUNTIME_C


def emit_mt_selftest(config: dict) -> str:
    """返回运行时 + 自测 main() 的完整 C 程序（退出码 0 = 全部通过）。"""
    return emit_mt_runtime(config) + MT_SELFTEST_C


# ---------------------------------------------------------------------------
# 2. C 运行时
# ---------------------------------------------------------------------------

MT_RUNTIME_C = r"""
/* =====================================================================
 * Rosoto 多核任务运行时（work-stealing 调度器）
 * ---------------------------------------------------------------------
 * 多核默认：worker 数 = min(在线核数, cgroup 配额)，除非 Rosoto.toml
 * [core] multicore=false 显式单核（确定性串行，语义不变）。
 *
 * 调度结构：
 *   每 worker 一个本地队列（互斥保护的单链；owner 头部进出 = LIFO 局部性，
 *   窃取者从头部偷 = 无锁热点分散）。空闲 worker 随机探测他核队列。
 *   任务对象走线程本地空闲链复用 —— spawn/run 热路径零 malloc。
 *
 * 每任务内存预算：RosotoTask 32B（fn 8 + ctx 8 + join 8 + next 8），
 * 线程本地缓存上限 256 个 = 8KB/线程；channel 每槽 8B + cap 可配。
 * ===================================================================== */
#ifndef ROSOTO_MT_RUNTIME_INCLUDED
#define ROSOTO_MT_RUNTIME_INCLUDED

#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sched.h>

#ifndef ROSOTO_CACHELINE
#define ROSOTO_CACHELINE 64
#endif
#ifndef ROSOTO_NOW_NS_DEFINED
#define ROSOTO_NOW_NS_DEFINED
static uint64_t rosoto_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
#endif

typedef void (*RosotoTaskFn)(void *ctx);
typedef void (*RosotoRangeFn)(void *user, int64_t lo, int64_t hi);

/* ---- 1. Join（任务收敛；等价 SPEC 的 JoinHandle.join()） ---- */
typedef struct RosotoJoin {
    pthread_mutex_t m;
    pthread_cond_t c;
    int pending;
    int done;
} RosotoJoin;

void rosoto_join_init(RosotoJoin *j) {
    pthread_mutex_init(&j->m, NULL);
    pthread_cond_init(&j->c, NULL);
    j->pending = 0;
    j->done = 0;
}
static void rosoto_join_add(RosotoJoin *j, int n) {
    pthread_mutex_lock(&j->m);
    j->pending += n;
    if (j->pending <= 0) { j->done = 1; pthread_cond_broadcast(&j->c); }
    pthread_mutex_unlock(&j->m);
}
static void rosoto_join_fire(RosotoJoin *j) {
    pthread_mutex_lock(&j->m);
    if (--j->pending <= 0) { j->done = 1; pthread_cond_broadcast(&j->c); }
    pthread_mutex_unlock(&j->m);
}
void rosoto_join_wait(RosotoJoin *j) {
    pthread_mutex_lock(&j->m);
    while (!j->done) pthread_cond_wait(&j->c, &j->m);
    pthread_mutex_unlock(&j->m);
}
void rosoto_join_destroy(RosotoJoin *j) {
    pthread_mutex_destroy(&j->m);
    pthread_cond_destroy(&j->c);
}

/* ---- 2. 任务对象（线程本地空闲链复用，热路径零 malloc） ---- */
typedef struct RosotoTask {
    RosotoTaskFn fn;
    void *ctx;
    RosotoJoin *join;
    struct RosotoTask *next;
} RosotoTask;

#define ROSOTO_TASK_CACHE_MAX 256
static __thread RosotoTask *g_task_cache;
static __thread int g_task_cache_n;

static RosotoTask *rosoto_task_alloc(void) {
    if (g_task_cache) {
        RosotoTask *t = g_task_cache;
        g_task_cache = t->next;
        g_task_cache_n--;
        return t;
    }
    return (RosotoTask *)malloc(sizeof(RosotoTask));
}
static void rosoto_task_free(RosotoTask *t) {
    if (g_task_cache_n < ROSOTO_TASK_CACHE_MAX) {
        t->next = g_task_cache;
        g_task_cache = t;
        g_task_cache_n++;
    } else {
        free(t);
    }
}

/* ---- 3. 每 worker 队列（互斥单链；owner/窃取者都从头部取） ---- */
typedef struct RosotoQueue {
    pthread_mutex_t m;
    RosotoTask *head;
    int count;
} RosotoQueue;

static void rosoto_q_push(RosotoQueue *q, RosotoTask *t) {
    pthread_mutex_lock(&q->m);
    t->next = q->head;
    q->head = t;
    q->count++;
    pthread_mutex_unlock(&q->m);
}
static RosotoTask *rosoto_q_pop(RosotoQueue *q) {
    pthread_mutex_lock(&q->m);
    RosotoTask *t = q->head;
    if (t) {
        q->head = t->next;
        q->count--;
    }
    pthread_mutex_unlock(&q->m);
    return t;
}

/* ---- 4. 线程安全计数器（缓存行填充，防伪共享） ---- */
typedef struct RosotoCounter {
    uint64_t v;
    char pad[ROSOTO_CACHELINE - sizeof(uint64_t)];
} RosotoCounter;

/* ---- 5. 池 ---- */
typedef struct RosotoWorker {
    pthread_t th;
    RosotoQueue q;
    unsigned seed;
    int id;
    int running;
    RosotoCounter executed;
    RosotoCounter stolen;
} RosotoWorker;

typedef struct RosotoPool {
    RosotoWorker *workers;
    int nworkers;
    int shutdown;
    int64_t queued;     /* 已入队未被取走（原子） */
    int64_t inflight;   /* 执行中（原子） */
    uint32_t rr;        /* spawn 轮转 */
    pthread_mutex_t idle_m;
    pthread_cond_t idle_c;
    int waiters;
    int affinity_mode;
    int ncpu;
} RosotoPool;

static RosotoPool *g_default_pool;
static pthread_mutex_t g_default_m = PTHREAD_MUTEX_INITIALIZER;

/* ---- 6. 核数探测：在线核数 + cgroup 配额（容器自动收敛） ---- */
static int rosoto_detect_workers(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    int w = n > 0 ? (int)n : 1;
    FILE *f = fopen("/sys/fs/cgroup/cpu.max", "r");   /* cgroup v2 */
    if (f) {
        char a[32] = {0}, b[32] = {0};
        if (fscanf(f, "%31s %31s", a, b) == 2 && strcmp(a, "max") != 0) {
            long q = atol(a), p = atol(b);
            if (q > 0 && p > 0) {
                int c = (int)((q + p - 1) / p);
                if (c < w) w = c;
            }
        }
        fclose(f);
    } else {
        f = fopen("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r");   /* cgroup v1 */
        if (f) {
            long q = 0;
            if (fscanf(f, "%ld", &q) == 1 && q > 0) {
                FILE *f2 = fopen("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r");
                long p = 100000;
                if (f2) { if (fscanf(f2, "%ld", &p) != 1) p = 100000; fclose(f2); }
                if (p > 0) {
                    int c = (int)((q + p - 1) / p);
                    if (c < w) w = c;
                }
            }
            fclose(f);
        }
    }
    return w < 1 ? 1 : w;
}

/* ---- 7. 绑核（compact=顺序；scatter=交错跨簇；LIST=显式清单） ---- */
static void rosoto_apply_affinity(RosotoPool *p, int wid) {
    int cpu = -1;
    switch (p->affinity_mode) {
    case 1:   /* compact：按序填充 */
        cpu = wid % p->ncpu;
        break;
    case 2:   /* scatter：交错到两半（跨 CCX/NUMA 的启发式展开） */
        if (p->ncpu >= 2) cpu = (wid / 2) + (wid % 2) * (p->ncpu / 2);
        else cpu = 0;
        cpu %= p->ncpu;
        break;
    case 3:   /* 显式列表 [0,1,2] */ {
        int nlist = ROSOTO_AFFINITY_LIST_N;   /* 运行期变量，避开常量除零告警 */
        if (nlist > 0) cpu = rosoto_affinity_cpus[wid % nlist];
        break;
    }
    default:
        return;
    }
    if (cpu >= 0 && cpu < CPU_SETSIZE) {
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(cpu, &set);
        (void)pthread_setaffinity_np(pthread_self(), sizeof set, &set);
    }
}

/* ---- 8. 唤醒原语（谓词都在 idle_m 内读，避免丢失唤醒） ---- */
static void rosoto_pool_signal_one(RosotoPool *p) {
    pthread_mutex_lock(&p->idle_m);
    pthread_cond_signal(&p->idle_c);
    pthread_mutex_unlock(&p->idle_m);
}
static void rosoto_pool_signal_all(RosotoPool *p) {
    pthread_mutex_lock(&p->idle_m);
    pthread_cond_broadcast(&p->idle_c);
    pthread_mutex_unlock(&p->idle_m);
}

/* ---- 9. worker 主循环 ---- */
static void *rosoto_worker_run(void *arg);

typedef struct RosotoWorkerArg { RosotoPool *pool; RosotoWorker *w; } RosotoWorkerArg;

static void *rosoto_worker_run(void *arg) {
    RosotoWorkerArg *wa = (RosotoWorkerArg *)arg;
    RosotoPool *p = wa->pool;
    RosotoWorker *w = wa->w;
    free(wa);
    rosoto_apply_affinity(p, w->id);
    w->running = 1;
    w->seed = (unsigned)(rosoto_now_ns() ^ (uint64_t)(w->id * 2654435761u)) | 1u;

    for (;;) {
        RosotoTask *t = rosoto_q_pop(&w->q);          /* 1) 本地队列（LIFO） */
        if (!t) {                                      /* 2) 窃取他核 */
            for (int i = 0; i < p->nworkers && !t; i++) {
                w->seed = w->seed * 1103515245u + 12345u;
                int v = (int)(w->seed >> 16) % p->nworkers;
                if (v == w->id) continue;
                t = rosoto_q_pop(&p->workers[v].q);
                if (t) w->stolen.v++;
            }
        }
        if (t) {
            __atomic_sub_fetch(&p->queued, 1, __ATOMIC_RELAXED);
            __atomic_add_fetch(&p->inflight, 1, __ATOMIC_RELAXED);
            RosotoJoin *j = t->join;
            t->fn(t->ctx);
            rosoto_task_free(t);
            if (j) rosoto_join_fire(j);
            w->executed.v++;
            if (__atomic_sub_fetch(&p->inflight, 1, __ATOMIC_RELAXED) == 0)
                rosoto_pool_signal_all(p);            /* 帧屏障 wait_idle 可醒 */
            continue;
        }
        /* 3) 无任务：挂起等唤醒（谓词 = queued==0） */
        pthread_mutex_lock(&p->idle_m);
        p->waiters++;
        while (!p->shutdown && __atomic_load_n(&p->queued, __ATOMIC_RELAXED) == 0)
            pthread_cond_wait(&p->idle_c, &p->idle_m);
        p->waiters--;
        int stop = p->shutdown && __atomic_load_n(&p->queued, __ATOMIC_RELAXED) == 0;
        pthread_mutex_unlock(&p->idle_m);
        if (stop) break;
    }
    return NULL;
}

/* ---- 10. 池生命周期 ---- */
void rosoto_pool_destroy(RosotoPool *p);   /* 前向声明（创建失败回退路径用） */

RosotoPool *rosoto_pool_create(int workers, int affinity_mode) {
    if (workers <= 0) workers = (ROSOTO_WORKERS > 0) ? ROSOTO_WORKERS : rosoto_detect_workers();
    if (workers <= 0) workers = 1;
    RosotoPool *p = (RosotoPool *)calloc(1, sizeof(RosotoPool));
    if (!p) return NULL;
    p->workers = (RosotoWorker *)calloc((size_t)workers, sizeof(RosotoWorker));
    if (!p->workers) { free(p); return NULL; }
    p->nworkers = workers;
    p->affinity_mode = affinity_mode;
    p->ncpu = (int)sysconf(_SC_NPROCESSORS_ONLN);
    if (p->ncpu < 1) p->ncpu = 1;
    pthread_mutex_init(&p->idle_m, NULL);
    pthread_cond_init(&p->idle_c, NULL);
    for (int i = 0; i < workers; i++) {
        RosotoWorker *w = &p->workers[i];
        w->id = i;
        pthread_mutex_init(&w->q.m, NULL);
        if (workers > 1) {
            RosotoWorkerArg *wa = (RosotoWorkerArg *)malloc(sizeof(RosotoWorkerArg));
            if (!wa) { p->nworkers = i; rosoto_pool_destroy(p); return NULL; }
            wa->pool = p;
            wa->w = w;
            if (pthread_create(&w->th, NULL, rosoto_worker_run, wa) != 0) {
                free(wa);
                p->nworkers = i;
                rosoto_pool_destroy(p);
                return NULL;
            }
        }
    }
    return p;
}

/* 单核确定性模式：workers==1 不建线程，spawn 即内联执行 */
static inline bool rosoto_pool_serial(const RosotoPool *p) { return p->nworkers <= 1; }

void rosoto_pool_spawn(RosotoPool *p, RosotoTaskFn fn, void *ctx, RosotoJoin *join) {
    RosotoTask *t = rosoto_task_alloc();
    if (!t) {   /* 分配失败兜底：内联执行，保持语义 */
        fn(ctx);
        if (join) rosoto_join_fire(join);
        return;
    }
    t->fn = fn;
    t->ctx = ctx;
    t->join = join;
    t->next = NULL;
    if (rosoto_pool_serial(p)) {   /* 显式单核：确定性串行 */
        fn(ctx);
        rosoto_task_free(t);
        if (join) rosoto_join_fire(join);
        return;
    }
    __atomic_add_fetch(&p->queued, 1, __ATOMIC_RELAXED);
    uint32_t idx = __atomic_add_fetch(&p->rr, 1, __ATOMIC_RELAXED) % (uint32_t)p->nworkers;
    rosoto_q_push(&p->workers[idx].q, t);
    rosoto_pool_signal_one(p);
}

int rosoto_pool_workers(RosotoPool *p) { return p->nworkers; }

/* 帧屏障：等到队列清空且无在飞任务（游戏帧末收敛 / 阶段同步） */
void rosoto_pool_wait_idle(RosotoPool *p) {
    if (rosoto_pool_serial(p)) return;   /* 串行模式 spawn 即完成 */
    pthread_mutex_lock(&p->idle_m);
    while (__atomic_load_n(&p->queued, __ATOMIC_RELAXED) != 0 ||
           __atomic_load_n(&p->inflight, __ATOMIC_RELAXED) != 0)
        pthread_cond_wait(&p->idle_c, &p->idle_m);
    pthread_mutex_unlock(&p->idle_m);
}

uint64_t rosoto_pool_stat_exec(RosotoPool *p) {
    uint64_t s = 0;
    for (int i = 0; i < p->nworkers; i++) s += p->workers[i].executed.v;
    return s;
}
uint64_t rosoto_pool_stat_steal(RosotoPool *p) {
    uint64_t s = 0;
    for (int i = 0; i < p->nworkers; i++) s += p->workers[i].stolen.v;
    return s;
}

void rosoto_pool_destroy(RosotoPool *p) {
    if (!p) return;
    p->shutdown = 1;
    rosoto_pool_signal_all(p);
    for (int i = 0; i < p->nworkers; i++) {
        RosotoWorker *w = &p->workers[i];
        if (w->running) pthread_join(w->th, NULL);
        /* 清理残余任务 */
        RosotoTask *t = rosoto_q_pop(&w->q);
        while (t) {
            if (t->join) rosoto_join_fire(t->join);
            free(t);
            t = rosoto_q_pop(&w->q);
        }
        pthread_mutex_destroy(&w->q.m);
    }
    pthread_mutex_destroy(&p->idle_m);
    pthread_cond_destroy(&p->idle_c);
    free(p->workers);
    free(p);
}

/* 默认全局池：多核默认开（第一次使用时惰性创建） */
RosotoPool *rosoto_pool_default(void) {
    pthread_mutex_lock(&g_default_m);
    if (!g_default_pool) {
        int w = (ROSOTO_WORKERS > 0) ? ROSOTO_WORKERS : rosoto_detect_workers();
        if (w > 1) g_default_pool = rosoto_pool_create(w, ROSOTO_AFFINITY_MODE);
        else g_default_pool = rosoto_pool_create(1, 0);   /* 显式单核 */
    }
    pthread_mutex_unlock(&g_default_m);
    return g_default_pool;
}

/* ---- 11. parfor：静态分块 + 可窃取兜底（reduction 由用户原子/分块收敛） ---- */
typedef struct RosotoRangeTask {
    RosotoRangeFn fn;
    void *user;
    int64_t lo, hi;
} RosotoRangeTask;

static void rosoto_range_run(void *ctx) {
    RosotoRangeTask *r = (RosotoRangeTask *)ctx;
    r->fn(r->user, r->lo, r->hi);
}

void rosoto_pool_parallel_for(RosotoPool *p, int64_t lo, int64_t hi, int64_t grain,
                              RosotoRangeFn fn, void *user) {
    int64_t n = hi - lo;
    if (n <= 0) return;
    if (grain <= 0) grain = ROSOTO_PARFOR_GRAIN;
    if (rosoto_pool_serial(p) || n <= grain) {   /* 显式单核/小任务：串行 */
        fn(user, lo, hi);
        return;
    }
    int64_t chunks = (n + grain - 1) / grain;
    int64_t max_chunks = (int64_t)p->nworkers * 4;
    if (chunks > max_chunks) chunks = max_chunks;
    if (chunks > 1024) chunks = 1024;
    int64_t per = (n + chunks - 1) / chunks;

    RosotoRangeTask *rts = (RosotoRangeTask *)malloc((size_t)chunks * sizeof(RosotoRangeTask));
    if (!rts) { fn(user, lo, hi); return; }
    RosotoJoin join;
    rosoto_join_init(&join);
    rosoto_join_add(&join, (int)chunks - 1);   /* 第 0 块调用者内联 */

    for (int64_t i = 1; i < chunks; i++) {
        rts[i].fn = fn;
        rts[i].user = user;
        rts[i].lo = lo + i * per;
        rts[i].hi = (i == chunks - 1) ? hi : lo + (i + 1) * per;
        if (rts[i].lo >= rts[i].hi) { rosoto_join_fire(&join); continue; }
        RosotoTask *t = rosoto_task_alloc();
        if (!t) { fn(user, rts[i].lo, rts[i].hi); rosoto_join_fire(&join); continue; }
        t->fn = rosoto_range_run;
        t->ctx = &rts[i];
        t->join = &join;
        t->next = NULL;
        __atomic_add_fetch(&p->queued, 1, __ATOMIC_RELAXED);
        uint32_t idx = (uint32_t)i % (uint32_t)p->nworkers;
        rosoto_q_push(&p->workers[idx].q, t);
        rosoto_pool_signal_one(p);
    }
    fn(user, lo, lo + per < hi ? lo + per : hi);   /* 第 0 块内联 */
    rosoto_join_wait(&join);
    rosoto_join_destroy(&join);
    free(rts);
}

/* ---- 12. MPMC channel（有界环形；任务流水线 / DB 流水线） ---- */
typedef struct RosotoChan {
    pthread_mutex_t m;
    pthread_cond_t not_empty, not_full;
    void **ring;
    uint32_t cap, head, count;
    int closed;
} RosotoChan;

RosotoChan *rosoto_chan_open(uint32_t cap) {
    if (cap == 0) cap = 1;
    RosotoChan *ch = (RosotoChan *)calloc(1, sizeof(RosotoChan));
    if (!ch) return NULL;
    ch->ring = (void **)calloc(cap, sizeof(void *));
    if (!ch->ring) { free(ch); return NULL; }
    ch->cap = cap;
    pthread_mutex_init(&ch->m, NULL);
    pthread_cond_init(&ch->not_empty, NULL);
    pthread_cond_init(&ch->not_full, NULL);
    return ch;
}
bool rosoto_chan_send(RosotoChan *ch, void *msg) {
    pthread_mutex_lock(&ch->m);
    while (ch->count == ch->cap && !ch->closed)
        pthread_cond_wait(&ch->not_full, &ch->m);
    if (ch->closed) { pthread_mutex_unlock(&ch->m); return false; }
    ch->ring[(ch->head + ch->count) % ch->cap] = msg;
    ch->count++;
    pthread_cond_signal(&ch->not_empty);
    pthread_mutex_unlock(&ch->m);
    return true;
}
bool rosoto_chan_try_send(RosotoChan *ch, void *msg) {
    pthread_mutex_lock(&ch->m);
    if (ch->closed || ch->count == ch->cap) { pthread_mutex_unlock(&ch->m); return false; }
    ch->ring[(ch->head + ch->count) % ch->cap] = msg;
    ch->count++;
    pthread_cond_signal(&ch->not_empty);
    pthread_mutex_unlock(&ch->m);
    return true;
}
bool rosoto_chan_recv(RosotoChan *ch, void **out) {
    pthread_mutex_lock(&ch->m);
    while (ch->count == 0 && !ch->closed)
        pthread_cond_wait(&ch->not_empty, &ch->m);
    if (ch->count == 0) { pthread_mutex_unlock(&ch->m); return false; }  /* 关闭且空 */
    if (out) *out = ch->ring[ch->head];
    ch->head = (ch->head + 1) % ch->cap;
    ch->count--;
    pthread_cond_signal(&ch->not_full);
    pthread_mutex_unlock(&ch->m);
    return true;
}
bool rosoto_chan_try_recv(RosotoChan *ch, void **out) {
    pthread_mutex_lock(&ch->m);
    if (ch->count == 0) { pthread_mutex_unlock(&ch->m); return false; }
    if (out) *out = ch->ring[ch->head];
    ch->head = (ch->head + 1) % ch->cap;
    ch->count--;
    pthread_cond_signal(&ch->not_full);
    pthread_mutex_unlock(&ch->m);
    return true;
}
void rosoto_chan_close(RosotoChan *ch) {
    pthread_mutex_lock(&ch->m);
    ch->closed = 1;
    pthread_cond_broadcast(&ch->not_empty);
    pthread_cond_broadcast(&ch->not_full);
    pthread_mutex_unlock(&ch->m);
}
void rosoto_chan_destroy(RosotoChan *ch) {
    if (!ch) return;
    pthread_mutex_destroy(&ch->m);
    pthread_cond_destroy(&ch->not_empty);
    pthread_cond_destroy(&ch->not_full);
    free(ch->ring);
    free(ch);
}

#endif /* ROSOTO_MT_RUNTIME_INCLUDED */
"""

# ---------------------------------------------------------------------------
# 3. 自测程序
# ---------------------------------------------------------------------------

MT_SELFTEST_C = r"""
/* =====================================================================
 * Rosoto 多核运行时自测：gcc -O2 -pthread 编译后运行，退出码 0 = 全部通过
 * ===================================================================== */
static int g_fail = 0;
#define CHECK(cond, name) do { \
    if (cond) printf("  [PASS] %s\n", name); \
    else { printf("  [FAIL] %s\n", name); g_fail++; } \
} while (0)

static int64_t g_sum;
static void range_sum(void *user, int64_t lo, int64_t hi) {
    (void)user;
    int64_t s = 0;
    for (int64_t i = lo; i < hi; i++) s += i;
    __atomic_add_fetch(&g_sum, s, __ATOMIC_RELAXED);
}

/* 逐项无状态混合负载：可分段相加（parfor 分块友好）且不可被折叠成闭式解，
 * 用于公平的串行/并行计时对比 */
static inline int64_t mix_item(int64_t i) {
    return (int64_t)(((uint64_t)i * 6364136223846793005ull) >> 33);
}
static __attribute__((noinline)) int64_t mix_sum(int64_t lo, int64_t hi) {
    int64_t s = 0;
    for (int64_t i = lo; i < hi; i++) s += mix_item(i);
    return s;
}
static void range_mix(void *user, int64_t lo, int64_t hi) {
    __atomic_add_fetch((int64_t *)user, mix_sum(lo, hi), __ATOMIC_RELAXED);
}

static int g_counter;
static void task_bump(void *ctx) { (void)ctx; __atomic_add_fetch(&g_counter, 1, __ATOMIC_RELAXED); }

typedef struct NestCtx { RosotoPool *pool; int depth; } NestCtx;
static NestCtx g_nest_ctx[64];   /* 子任务 ctx 槽位（原子分配，避免 TLS 复用竞态） */
static int g_nest_slot;
static void task_nest(void *ctx) {
    NestCtx *n = (NestCtx *)ctx;
    if (n->depth > 0) {
        for (int i = 0; i < 2; i++) {
            int s = __atomic_fetch_add(&g_nest_slot, 1, __ATOMIC_RELAXED);
            if (s < 64) {
                g_nest_ctx[s].pool = n->pool;
                g_nest_ctx[s].depth = n->depth - 1;
                rosoto_pool_spawn(n->pool, task_nest, &g_nest_ctx[s], NULL);
            }
        }
    }
    __atomic_add_fetch(&g_counter, 1, __ATOMIC_RELAXED);
}

static int64_t g_consumed;
static void task_consume(void *ctx) {
    RosotoChan *ch = (RosotoChan *)ctx;
    void *m;
    int64_t s = 0;
    while (rosoto_chan_recv(ch, &m)) s += (int64_t)(intptr_t)m;
    __atomic_add_fetch(&g_consumed, s, __ATOMIC_RELAXED);
}

int main(void) {
    printf("[mt selftest]\n");
    RosotoPool *pool = rosoto_pool_default();
    printf("  [info] workers=%d（多核默认；1 = 显式单核确定性模式）\n", rosoto_pool_workers(pool));

    /* 1. parfor 归约求和（与公式核对） */
    {
        g_sum = 0;
        int64_t n = 10000000;
        uint64_t t0 = rosoto_now_ns();
        rosoto_pool_parallel_for(pool, 0, n, 0, range_sum, NULL);
        uint64_t dt = rosoto_now_ns() - t0;
        int64_t expect = n * (n - 1) / 2;
        CHECK(g_sum == expect, "parfor 归约求和 0..10M（静态分块+可窃取）");
        printf("  [info] parfor: %.1f M iters/s（%d workers）\n",
               dt ? (double)n / (double)dt * 1000.0 : 0.0, rosoto_pool_workers(pool));
    }

    /* 2. spawn + join 收敛 2000 个任务 */
    {
        g_counter = 0;
        RosotoJoin join;
        rosoto_join_init(&join);
        rosoto_join_add(&join, 2000);
        for (int i = 0; i < 2000; i++) rosoto_pool_spawn(pool, task_bump, NULL, &join);
        rosoto_join_wait(&join);
        CHECK(g_counter == 2000, "spawn/join：2000 任务全部收敛");
        rosoto_join_destroy(&join);
    }

    /* 3. 嵌套 spawn + 帧屏障 wait_idle（1 + 2 + 4 任务树） */
    {
        g_counter = 0;
        NestCtx root = { pool, 2 };
        rosoto_pool_spawn(pool, task_nest, &root, NULL);
        rosoto_pool_wait_idle(pool);
        CHECK(g_counter == 7, "嵌套 spawn + wait_idle 帧屏障（任务树收敛）");
    }

    /* 4. channel 语义（单线程 FIFO + 关闭语义，任何模式都验） */
    {
        int ok = 1;
        RosotoChan *ch = rosoto_chan_open(2);
        ok = ok && rosoto_chan_try_send(ch, (void *)(intptr_t)1);
        ok = ok && rosoto_chan_try_send(ch, (void *)(intptr_t)2);
        ok = ok && !rosoto_chan_try_send(ch, (void *)(intptr_t)3);   /* 满则拒绝 */
        void *m = NULL;
        ok = ok && rosoto_chan_try_recv(ch, &m) && (int64_t)(intptr_t)m == 1;  /* FIFO */
        ok = ok && rosoto_chan_try_recv(ch, &m) && (int64_t)(intptr_t)m == 2;
        ok = ok && !rosoto_chan_try_recv(ch, &m);                    /* 空则拒绝 */
        rosoto_chan_close(ch);
        ok = ok && !rosoto_chan_send(ch, (void *)(intptr_t)4);       /* 关闭后拒发 */
        ok = ok && !rosoto_chan_recv(ch, &m);                        /* 关闭且空 → 结束 */
        CHECK(ok, "channel 语义：FIFO/满拒/空拒/关闭收敛");
        rosoto_chan_destroy(ch);
    }

    /* 5. MPMC channel 并发：生产者在主线程（避免阻塞任务占满 worker 互锁），
     *    双消费者任务求和 5 万条 */
    if (rosoto_pool_workers(pool) > 1) {
        g_consumed = 0;
        RosotoChan *ch = rosoto_chan_open(256);
        RosotoJoin join;
        rosoto_join_init(&join);
        rosoto_join_add(&join, 2);
        rosoto_pool_spawn(pool, task_consume, ch, &join);
        rosoto_pool_spawn(pool, task_consume, ch, &join);
        /* 主线程生产 5 万条后关闭；消费者并行消费 */
        for (int64_t i = 1; i <= 50000; i++) rosoto_chan_send(ch, (void *)(intptr_t)i);
        rosoto_chan_close(ch);
        rosoto_join_wait(&join);
        int64_t expect = (int64_t)50000 * 50001 / 2;
        CHECK(g_consumed == expect, "MPMC channel：5 万消息双消费者求和");
        rosoto_join_destroy(&join);
        rosoto_chan_destroy(ch);
    } else {
        printf("  [SKIP] MPMC 并发 channel（单核确定性模式）\n");
    }
    /* 6. 串行 vs 并行耗时（同一种混合负载，公平对比；信息性） */
    {
        int64_t n = 10000000;
        int64_t s = mix_sum(0, n);          /* 串行基线（LCG 混合负载，不可闭式折叠） */
        uint64_t t0 = rosoto_now_ns();
        s = mix_sum(0, n);
        uint64_t serial_ns = rosoto_now_ns() - t0;
        int64_t g_mix = 0;
        t0 = rosoto_now_ns();
        rosoto_pool_parallel_for(pool, 0, n, 0, range_mix, &g_mix);
        uint64_t par_ns = rosoto_now_ns() - t0;
        CHECK(g_mix == s, "串行/并行结果一致（混合负载）");
        printf("  [info] 串行 %.1f ms | 并行 %.1f ms | 加速比 %.2fx\n",
               (double)serial_ns / 1e6, (double)par_ns / 1e6,
               par_ns ? (double)serial_ns / (double)par_ns : 0.0);
    }

    printf("  [info] 统计: executed=%llu stolen=%llu\n",
           (unsigned long long)rosoto_pool_stat_exec(pool),
           (unsigned long long)rosoto_pool_stat_steal(pool));
    rosoto_pool_destroy(pool);
    printf("SELFTEST %s (fail=%d)\n", g_fail == 0 ? "PASS" : "FAIL", g_fail);
    return g_fail == 0 ? 0 : 1;
}
"""

# ---------------------------------------------------------------------------
# 4. 命令行入口
# ---------------------------------------------------------------------------

def _build_arg_parser():
    p = argparse.ArgumentParser(
        prog="rosoto_mt.py",
        description="发射 Rosoto 多核任务运行时 C 运行时（work-stealing，多核默认）",
    )
    p.add_argument("--threads", type=int, default=None,
                   help="worker 数，0=自动（默认 %d；multicore=false 时为 1）" % DEFAULT_CORE["threads"])
    p.add_argument("--affinity", default=None,
                   help="none|compact|scatter|[0,1,2]（默认 %s）" % DEFAULT_CORE["affinity"])
    p.add_argument("--grain", type=int, default=None,
                   help="parfor 分块粒度（默认 %d）" % DEFAULT_CORE["grain"])
    p.add_argument("--multicore", type=_bool_arg, default=None, metavar="BOOL",
                   help="多核开关，false=显式单核确定性模式（默认 %s）" % DEFAULT_CORE["multicore"])
    p.add_argument("--preempt", type=_bool_arg, default=None, metavar="BOOL",
                   help="安全点抢占（默认 %s）" % DEFAULT_CORE["preempt"])
    return p


def _core_from_args(ns):
    core = dict(DEFAULT_CORE)
    for key in ("threads", "affinity", "grain", "multicore", "preempt"):
        val = getattr(ns, key)
        if val is not None:
            core[key] = val
    return {"core": core}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    mode = "emit"
    if args and args[0] in ("emit", "selftest"):
        mode = args.pop(0)
    elif args and not args[0].startswith("-"):
        sys.stderr.write("rosoto_mt.py: 未知子命令 %r（支持 emit|selftest）\n" % args[0])
        return 2

    ns = _build_arg_parser().parse_args(args)
    try:
        cfg = _core_from_args(ns)
        out = emit_mt_selftest(cfg) if mode == "selftest" else emit_mt_runtime(cfg)
    except ValueError as e:
        sys.stderr.write("rosoto_mt.py: %s\n" % e)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
