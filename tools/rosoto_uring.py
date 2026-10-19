#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rosoto io_uring 网络后端运行时发射器
====================================

`tools/rosoto.py` 的 epoll 版运行时主打通用性；本模块补上 Rosoto.toml [net]
声明的 `backend = "io_uring"` 高性能后端：把一段**自包含**的 C99 运行时打到
stdout（或由 `emit_uring_runtime()` 返回字符串），交给任意 C 编译器编译。

设计取向（与 Rosoto「原生编译、多核默认、网络 IO 极致」的调性一致）：

* 纯 `syscall(__NR_io_uring_setup / enter / register)`，**不依赖 liburing**，
  也没有其他外部依赖；
* 单线程 reactor：一个 io_uring 实例 + 一个事件循环，无锁、无 malloc 热点；
* 每连接固定 92 字节结构体 + 全局固定缓冲池（空闲栈复用），
  100 万连接常驻内存 ≈ 125 MB（运行时源码内有逐项预算注释）；
* max_conns 硬上限 fail-fast 拒绝；背压三策略 drop / close / block 可配；
* 回调接口与 epoll 版对应（on_connect / on_data / on_close），便于将来把
  `rosoto_echo_serve()` 的后端整体切换。

用法（命令行）::

    python3 tools/rosoto_uring.py emit [--max-conns N] [--backpressure drop|close|block]
                                      [--recv-buffer N] [--send-buffer N]
                                      [--tcp-nodelay true|false] [--reuse-port true|false]
                                      [--backlog N] [--pool-buffers N] [--ring-entries N]

用法（库）::

    from rosoto_uring import emit_uring_runtime
    c_src = emit_uring_runtime({"net": {"max_conns": 1000000, "backpressure": "drop"}})
"""

import argparse
import sys

__all__ = ["emit_uring_runtime", "DEFAULT_NET", "main"]

# ---------------------------------------------------------------------------
# 0. 默认配置（与 Rosoto.toml [net] 节对齐；backlog / pool_buffers / ring_entries
#    为运行时细化项，Rosoto.toml 未声明时取这里的默认值）
# ---------------------------------------------------------------------------

DEFAULT_NET = {
    "backend": "io_uring",
    "max_conns": 1000000,     # 硬上限，超限拒绝连接（fail-fast）
    "recv_buffer": 4096,      # 每个池缓冲字节数（recv/send 共用）
    "send_buffer": 4096,      # 每连接发送限额（排队 + 在飞字节数）
    "tcp_nodelay": True,
    "reuse_port": True,
    "backpressure": "drop",   # drop | close | block
    "backlog": 1024,
    "pool_buffers": 8192,     # 全局缓冲池块数（与连接数无关）
    "ring_entries": 4096,     # SQE 环深度（内核会向上取整到 2 的幂）
}

BACKPRESSURE_CODES = {"drop": 0, "close": 1, "block": 2}

_INT_RANGES = {
    "max_conns": (1, 4 * 1024 * 1024),     # 槽位 id 占 user_data 低 32 位
    "recv_buffer": (64, 1 << 20),
    "send_buffer": (64, 1 << 20),
    "backlog": (1, 65535),
    "pool_buffers": (1, 1 << 20),
    "ring_entries": (64, 1 << 16),
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


def _net_section(config):
    """兼容两种入参：完整配置 `{"net": {...}}` 或扁平的 net 配置 `{"max_conns": ...}`。"""
    net = dict(DEFAULT_NET)
    if not config:
        return net
    if not isinstance(config, dict):
        raise ValueError(f"config 需要 dict，得到: {type(config).__name__}")
    src = config.get("net") if isinstance(config.get("net"), dict) else config
    for k, v in src.items():
        if k in net or k in ("backpressure",):
            net[k] = v
    return net


# ---------------------------------------------------------------------------
# 1. 发射器
# ---------------------------------------------------------------------------

def emit_uring_runtime(config: dict) -> str:
    """
    返回 io_uring 版非阻塞 TCP echo/reactor 运行时的 C99 源码字符串。

    config 可为完整配置（含 "net" 节）或扁平 net 配置；缺省项取 DEFAULT_NET。
    生成的 C 源码自包含：仅依赖 glibc + <linux/io_uring.h>（后者缺失时自动
    退化为最小 ABI 自足定义，保证 gcc -fsyntax-only 可通过）。
    """
    net = _net_section(config)

    max_conns = _as_int(net.get("max_conns"), "max_conns")
    recv_buffer = _as_int(net.get("recv_buffer"), "recv_buffer")
    send_buffer = _as_int(net.get("send_buffer"), "send_buffer")
    backlog = _as_int(net.get("backlog"), "backlog")
    pool_buffers = _as_int(net.get("pool_buffers"), "pool_buffers")
    ring_entries = _as_int(net.get("ring_entries"), "ring_entries")
    tcp_nodelay = 1 if _as_bool(net.get("tcp_nodelay"), "tcp_nodelay") else 0
    reuse_port = 1 if _as_bool(net.get("reuse_port"), "reuse_port") else 0

    bp = str(net.get("backpressure", "drop")).strip().lower()
    if bp not in BACKPRESSURE_CODES:
        raise ValueError(f"backpressure 需为 drop|close|block 之一，得到: {net.get('backpressure')!r}")
    bp_code = BACKPRESSURE_CODES[bp]

    # 发送队列深度必须是 2 的幂（结构体内用 & MASK 取模）
    sendq_depth = 4

    defines = f"""\
/* ==== Rosoto io_uring 运行时编译期配置（由 tools/rosoto_uring.py 注入） ==== */
#ifndef ROSOTO_NET_MAX_CONNS
#define ROSOTO_NET_MAX_CONNS {max_conns}      /* [net] max_conns：连接硬上限，超限 fail-fast 拒绝 */
#endif
#ifndef ROSOTO_RECV_BUF
#define ROSOTO_RECV_BUF {recv_buffer}         /* [net] recv_buffer：池缓冲块大小 */
#endif
#ifndef ROSOTO_SEND_BUF
#define ROSOTO_SEND_BUF {send_buffer}         /* [net] send_buffer：每连接发送限额（字节） */
#endif
#ifndef ROSOTO_TCP_NODELAY
#define ROSOTO_TCP_NODELAY {tcp_nodelay}          /* [net] tcp_nodelay */
#endif
#ifndef ROSOTO_REUSE_PORT
#define ROSOTO_REUSE_PORT {reuse_port}           /* [net] reuse_port */
#endif
#ifndef ROSOTO_BACKLOG
#define ROSOTO_BACKLOG {backlog}          /* listen(2) backlog */
#endif
#ifndef ROSOTO_POOL_BUFS
#define ROSOTO_POOL_BUFS {pool_buffers}        /* 全局缓冲池块数（与连接数无关） */
#endif
#ifndef ROSOTO_RING_ENTRIES
#define ROSOTO_RING_ENTRIES {ring_entries}       /* SQE 环深度 */
#endif
#define ROSOTO_SENDQ_DEPTH {sendq_depth}          /* 每连接发送队列深度（2 的幂） */
#define ROSOTO_BP_DROP  0
#define ROSOTO_BP_CLOSE 1
#define ROSOTO_BP_BLOCK 2
#ifndef ROSOTO_BACKPRESSURE
#define ROSOTO_BACKPRESSURE {bp_code}  /* [net] backpressure = "{bp}" */
#endif
"""

    return defines + URING_RUNTIME_C


# ---------------------------------------------------------------------------
# 2. C 运行时（自包含；纯 io_uring syscall，无 liburing）
# ---------------------------------------------------------------------------

URING_RUNTIME_C = r"""
/* =====================================================================
 * Rosoto 网络运行时 —— io_uring 单线程 reactor 版
 * ---------------------------------------------------------------------
 * 设计要点（回调与 tools/rosoto.py 的 epoll 版对应，便于后端切换）：
 *   1. 纯 syscall(__NR_io_uring_setup / enter / register)，不依赖 liburing；
 *   2. 单线程 reactor：一个 io_uring 实例、一个事件循环，无锁、无 malloc 热点；
 *   3. SQE 操作只用 4 种原语（语义见各 submit_* 函数注释）：
 *        IORING_OP_ACCEPT —— 监听槽常驻一个在飞 accept，完成即补，永不停听
 *        IORING_OP_RECV   —— 每连接最多 1 个在飞 recv（携带池缓冲）
 *        IORING_OP_SEND   —— 每连接最多 1 个在飞 send（发送队列串行泵出）
 *        IORING_OP_CLOSE  —— 连接收尾；在飞操作全部归零后才释放槽位
 *   4. 应用回调（由 serve() 以函数指针注入）：
 *        void on_connect(int fd)
 *        int  on_data(int fd, const void *buf, size_t n) -> NET_ACTION_KEEP/CLOSE
 *        void on_close(int fd)
 *      回调期间运行时维护 g_cur（当前连接），提供零拷贝回写助手
 *      rosoto_conn_echo() / 通用发送助手 rosoto_conn_send()。
 *   5. max_conns 硬上限：超限 fail-fast —— 新 fd 直接 close(2) 拒绝；
 *   6. 背压三策略（编译期 ROSOTO_BACKPRESSURE）：
 *        drop  —— 发送限额溢出：丢弃余量（丢数据、保连接），缓冲立即回池
 *        close —— 发送限额溢出：主动断开（保服务、舍连接）
 *        block —— 任务级阻塞重试：溢出数据挂入 per-conn hold 槽，由发送完成
 *                  事件驱动补发（经 SQE 队列排队重试），reactor 永不阻塞；
 *                  挂起期间停止武装 recv，用 TCP 流控把背压反传给对端
 *   7. 缓冲池：全局固定块 + 空闲栈，每连接 0 次 malloc；recv/send 共用同一
 *      池，回显走「缓冲所有权转移」零拷贝（不 memcpy）。
 *
 * ---------------------------------------------------------------------
 * 每连接内存预算（结构体 RosotoConn 逐项；sizeof 实测 92 字节）：
 *   fd 4 + gen 4 + peer_ip 4 + peer_port 2 + state 1 + flags 1   = 16
 *   rx_bid 4 + hold_bid 4 + hold_len 4 + wait_next 4             = 16
 *   sendq_id[4] 16 + sendq_len[4] 16 + sendq_off[4] 16           = 48
 *   sq_head/tail/send_active/retry 4 + queued_bytes 4 + inflight 4 = 12
 *   合计 92 B/连接 + 槽空闲栈项 4 B = 96 B/连接
 *
 * 100 万连接常驻内存估算（ROSOTO_NET_MAX_CONNS=1000000、RECV_BUF=4096、
 * POOL_BUFS=8192 时）：
 *   连接表 calloc(1e6, 92)        ≈ 92 MB（匿名惰性缺页，仅活跃槽实际驻留）
 *   槽空闲栈 uint32[1e6]          ≈  4 MB
 *   缓冲池 8192 × 4096            = 32 MB（与连接数无关，收发峰值上限）
 *   SQ 环 4096×64B + 数组         ≈ 0.3 MB
 *   CQ 环 8192×16B                ≈ 0.1 MB
 *   ---------------------------------------------------------------
 *   合计 ≈ 125 MB 常驻上限，摊到 100 万连接 ≈ 128 B/连接（含缓冲池）
 *   对比 epoll 版每连接 calloc(RosotoConn)+read 缓冲独占：数量级更低。
 * ===================================================================== */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/types.h>

/* ---- io_uring ABI：优先系统头文件；缺失时退化为最小自足定义 ---------- */
#if defined(__has_include)
#  if __has_include(<linux/io_uring.h>)
#    include <linux/io_uring.h>
#    define ROSOTO_HAVE_URING_H 1
#  endif
#elif defined(__linux__)
#  include <linux/io_uring.h>
#  define ROSOTO_HAVE_URING_H 1
#endif

#ifndef ROSOTO_HAVE_URING_H
/* 无 <linux/io_uring.h> 的环境（如裁剪过的交叉编译 sysroot）：以下为与
 * 内核 UAPI 布局严格一致的最小定义，只覆盖本运行时用到的字段/常量，
 * 保证 gcc -fsyntax-only / 离线编译照常通过。 */
struct io_uring_sqe {
    uint8_t  opcode;
    uint8_t  flags;
    uint16_t ioprio;
    int32_t  fd;
    uint64_t off;          /* union: off/addr2 */
    uint64_t addr;
    uint32_t len;
    uint32_t msg_flags;    /* union: msg_flags/accept_flags 同槽位 */
    uint64_t user_data;
    uint16_t buf_index;
    uint16_t personality;
    int32_t  splice_fd_in;
    uint64_t addr3;
    uint64_t __pad2;
};
struct io_uring_cqe {
    uint64_t user_data;
    int32_t  res;
    uint32_t flags;
};
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
#define IORING_OFF_SQ_RING       0ULL
#define IORING_OFF_CQ_RING       0x8000000ULL
#define IORING_OFF_SQES          0x10000000ULL
#define IORING_FEAT_SINGLE_MMAP  (1U << 0)
#define IORING_ENTER_GETEVENTS   (1U << 0)
#define IORING_REGISTER_BUFFERS  0
#define IORING_OP_ACCEPT         13   /* ABI 固定值，与内核 enum 顺序一致 */
#define IORING_OP_CLOSE          19
#define IORING_OP_SEND           26
#define IORING_OP_RECV           27
#endif

/* ---- 1. io_uring 系统调用封装（三个 syscall，等价 liburing 的薄层） ---- */
#ifndef __NR_io_uring_setup
#  define __NR_io_uring_setup    425   /* x86_64 / aarch64 / riscv64 通用编号 */
#  define __NR_io_uring_enter    426
#  define __NR_io_uring_register 427
#endif

/* 创建 io_uring 实例：entries=期望 SQE 深度；params 返回环布局与特性位 */
static int rosoto_sys_setup(unsigned entries, struct io_uring_params *p) {
    return (int)syscall(__NR_io_uring_setup, entries, p);
}
/* 提交 SQE / 等待 CQE：to_submit 本次消费的 SQE 数；min_complete+GETEVENTS
 * 表示至少等这么多个 CQE 返回（阻塞点，可被信号打断返回 EINTR） */
static int rosoto_sys_enter(int fd, unsigned to_submit, unsigned min_complete, unsigned flags) {
    return (int)syscall(__NR_io_uring_enter, fd, (unsigned long)to_submit,
                        (unsigned long)min_complete, flags, NULL, 0UL);
}
/* 注册内核侧长期资源（本运行时用 IORING_REGISTER_BUFFERS 钉住缓冲池页面） */
static int rosoto_sys_register(int fd, unsigned opcode, const void *arg, unsigned nr) {
    return (int)syscall(__NR_io_uring_register, fd, opcode, arg, nr);
}

/* ---- 2. user_data 编码：gen(24bit) | kind(8bit) | slot(32bit) ---------- */
/* gen 防陈旧 CQE：槽位复用后旧操作的完成事件可被识别丢弃；
 * kind 区分四种 SQE；slot 直接定位连接，免去 fd->conn 哈希表。 */
#define ROSOTO_UD(gen, kind, slot) \
    (((uint64_t)((gen) & 0xFFFFFFu) << 40) | \
     ((uint64_t)((kind) & 0xFFu) << 32) | ((uint64_t)(slot) & 0xFFFFFFFFu))
#define ROSOTO_UD_GEN(ud)  ((uint32_t)(((ud) >> 40) & 0xFFFFFFu))
#define ROSOTO_UD_KIND(ud) ((int)(((ud) >> 32) & 0xFFu))
#define ROSOTO_UD_SLOT(ud) ((uint32_t)((ud) & 0xFFFFFFFFu))

enum {
    ROSOTO_OP_ACCEPT = 1,
    ROSOTO_OP_RECV   = 2,
    ROSOTO_OP_SEND   = 3,
    ROSOTO_OP_CLOSE  = 4
};

/* ---- 3. 统计（诊断用；优雅退出时打印） ---- */
static uint64_t g_stat_accepted;
static uint64_t g_stat_rejected;   /* fail-fast 拒绝数（超 max_conns） */
static uint64_t g_stat_dropped;    /* drop 背压丢弃的发送块数 */
static uint64_t g_stat_bp_close;   /* close 背压触发的断开数 */
static uint64_t g_stat_bp_block;   /* block 背压挂起（hold）次数 */

/* ---- 4. 缓冲池：全局固定块 + 空闲栈（唯一的内存大块，只 malloc 一次） ---- */
typedef struct RosotoPool {
    uint32_t nbufs;     /* 块数 = ROSOTO_POOL_BUFS */
    uint32_t buflen;    /* 块大小 = ROSOTO_RECV_BUF */
    char    *mem;       /* nbufs * buflen 连续大块 */
    int32_t *stack;     /* 空闲块 id 栈 */
    uint32_t top;
} RosotoPool;
static RosotoPool g_pool;

static int rosoto_pool_init(uint32_t nbufs, uint32_t buflen) {
    g_pool.nbufs = nbufs;
    g_pool.buflen = buflen;
    g_pool.mem = (char *)malloc((size_t)nbufs * buflen);
    g_pool.stack = (int32_t *)malloc((size_t)nbufs * sizeof(int32_t));
    if (!g_pool.mem || !g_pool.stack) return -1;
    for (uint32_t i = 0; i < nbufs; i++) g_pool.stack[i] = (int32_t)i;
    g_pool.top = nbufs;
    return 0;
}
static char *rosoto_pool_buf(int32_t bid) {
    return g_pool.mem + (size_t)bid * g_pool.buflen;
}
/* 从空闲栈取一块；-1 = 池耗尽（调用方进入等待/丢弃路径） */
static int32_t rosoto_pool_get(void) {
    if (g_pool.top == 0) return -1;
    return g_pool.stack[--g_pool.top];
}
static void rosoto_pool_put(int32_t bid) {
    if (bid < 0) return;
    if (g_pool.top < g_pool.nbufs) g_pool.stack[g_pool.top++] = bid;
}

/* ---- 5. 连接表：连续数组 + 槽空闲栈（每连接 92B，绝不 per-conn malloc） ---- */
enum {
    ROSOTO_ST_FREE    = 0,
    ROSOTO_ST_ACTIVE  = 1,
    ROSOTO_ST_CLOSING = 2,   /* 已发 IORING_OP_CLOSE，等在飞操作归零 */
    ROSOTO_ST_CLOSED  = 3    /* close CQE 已回，可释放槽位 */
};
#define ROSOTO_CF_IN_WAIT 0x01   /* 已挂在 rx 等待链上（等缓冲） */

typedef struct RosotoConn {
    int32_t  fd;               /* 套接字；-1 = 空槽 */
    uint32_t gen;              /* 槽代数（slot_free 时 +1），防陈旧 CQE */
    uint32_t peer_ip;          /* 对端 IPv4（网络字节序） */
    uint16_t peer_port;        /* 对端端口（主机序） */
    uint8_t  state;            /* ROSOTO_ST_* */
    uint8_t  flags;            /* ROSOTO_CF_* */
    int32_t  rx_bid;           /* 在飞 RECV 的池缓冲 id；-1 = 无 */
    int32_t  hold_bid;         /* block 背压挂起缓冲 id；-1 = 无 */
    uint32_t hold_len;         /* 挂起数据长度 */
    int32_t  wait_next;        /* rx 等待链（侵入式单链，等缓冲的槽位） */
    int32_t  sendq_id[ROSOTO_SENDQ_DEPTH];    /* 发送 FIFO：缓冲 id */
    uint32_t sendq_len[ROSOTO_SENDQ_DEPTH];   /* 发送 FIFO：总长 */
    uint32_t sendq_off[ROSOTO_SENDQ_DEPTH];   /* 发送 FIFO：已发送偏移（SEND 可部分完成） */
    uint8_t  sq_head, sq_tail; /* 发送 FIFO 头尾（单调递增，& MASK 取下标） */
    uint8_t  send_active;      /* 是否有在飞 SEND（恒为 FIFO 头项） */
    uint8_t  retry;            /* 连续 -EAGAIN 计数（极端防御） */
    uint32_t queued_bytes;     /* 发送队列字节数（排队 + 在飞未发部分） */
    uint32_t inflight;         /* 在飞 op 数（RECV/SEND/CLOSE），归零才释放槽 */
} RosotoConn;                  /* = 92 字节 */

static RosotoConn *g_conns;
static uint32_t  *g_free_slots;
static uint32_t   g_free_top;
static uint32_t   g_nslots;
static uint64_t   g_nconns;
static uint64_t   g_max_conns;

/* rx 等待链：池无空闲缓冲时排队（不 malloc，链节点就是连接结构体自身） */
static int32_t g_wait_head = -1;
static int32_t g_wait_tail = -1;

static int32_t rosoto_slot_alloc(void) {
    if (g_free_top == 0) return -1;
    return (int32_t)g_free_slots[--g_free_top];
}
static void rosoto_slot_free(uint32_t slot) {
    RosotoConn *c = &g_conns[slot];
    c->fd = -1;
    c->state = ROSOTO_ST_FREE;
    c->flags = 0;
    c->gen = (c->gen + 1) & 0xFFFFFFu;   /* 代数递增，旧 user_data 全部失效 */
    if (g_free_top < g_nslots) g_free_slots[g_free_top++] = slot;
}

static void rosoto_wait_push(uint32_t slot) {
    RosotoConn *c = &g_conns[slot];
    if (c->flags & ROSOTO_CF_IN_WAIT) return;
    c->flags |= ROSOTO_CF_IN_WAIT;
    c->wait_next = -1;
    if (g_wait_tail < 0) g_wait_head = (int32_t)slot;
    else g_conns[g_wait_tail].wait_next = (int32_t)slot;
    g_wait_tail = (int32_t)slot;
}
static int32_t rosoto_wait_pop(void) {
    if (g_wait_head < 0) return -1;
    int32_t slot = g_wait_head;
    RosotoConn *c = &g_conns[slot];
    g_wait_head = c->wait_next;
    if (g_wait_head < 0) g_wait_tail = -1;
    c->wait_next = -1;
    c->flags &= (uint8_t)~ROSOTO_CF_IN_WAIT;
    return slot;
}

/* ---- 6. io_uring 双环（SQ 提交环 / CQ 完成环）映射与访问 ---- */
static int g_ring_fd = -1;
static struct io_uring_sqe *g_sqes;
static char   *g_sq_ring;
static char   *g_cq_ring;
static unsigned g_sq_entries;
static unsigned *g_sq_head, *g_sq_tail, *g_sq_mask, *g_sq_array, *g_sq_flags;
static unsigned *g_cq_head, *g_cq_tail, *g_cq_mask, *g_cq_overflow;
static struct io_uring_cqe *g_cqes;
static unsigned g_sq_unsubmitted;   /* 已写入 SQ 但尚未 io_uring_enter 的 SQE 数 */

/* 内核与用户态共享环内存：head/tail 读写需要 acquire/release 语义，
 * 用 gcc/clang __atomic 内建实现（无第三方依赖）。 */
static inline unsigned rosoto_load_acq(const unsigned *p) {
    return __atomic_load_n(p, __ATOMIC_ACQUIRE);
}
static inline void rosoto_store_rel(unsigned *p, unsigned v) {
    __atomic_store_n(p, v, __ATOMIC_RELEASE);
}

/* 创建实例并映射 SQ/CQ/SQE 三块内存；失败返回 -1 并置 errno
 * （ENOSYS/EPERM/EOPNOTSUPP 等表示内核未启用/被 seccomp 拦截） */
static int rosoto_ring_init(unsigned entries) {
    struct io_uring_params p;
    memset(&p, 0, sizeof p);
    g_ring_fd = rosoto_sys_setup(entries, &p);
    if (g_ring_fd < 0) return -1;

    size_t sq_sz = (size_t)p.sq_off.array + (size_t)p.sq_entries * sizeof(unsigned);
    size_t cq_sz = (size_t)p.cq_off.cqes + (size_t)p.cq_entries * sizeof(struct io_uring_cqe);
    if (p.features & IORING_FEAT_SINGLE_MMAP) {
        if (cq_sz > sq_sz) sq_sz = cq_sz;   /* 单映射特性：两环共用一块 */
        cq_sz = sq_sz;
    }
    g_sq_ring = (char *)mmap(NULL, sq_sz, PROT_READ | PROT_WRITE,
                             MAP_SHARED | MAP_POPULATE, g_ring_fd, IORING_OFF_SQ_RING);
    if (g_sq_ring == MAP_FAILED) return -1;
    if (p.features & IORING_FEAT_SINGLE_MMAP) {
        g_cq_ring = g_sq_ring;
    } else {
        g_cq_ring = (char *)mmap(NULL, cq_sz, PROT_READ | PROT_WRITE,
                                 MAP_SHARED | MAP_POPULATE, g_ring_fd, IORING_OFF_CQ_RING);
        if (g_cq_ring == MAP_FAILED) return -1;
    }
    g_sqes = (struct io_uring_sqe *)mmap(NULL, (size_t)p.sq_entries * sizeof(struct io_uring_sqe),
                                         PROT_READ | PROT_WRITE, MAP_SHARED | MAP_POPULATE,
                                         g_ring_fd, IORING_OFF_SQES);
    if (g_sqes == MAP_FAILED) return -1;

    g_sq_entries = p.sq_entries;
    g_sq_head  = (unsigned *)(g_sq_ring + p.sq_off.head);
    g_sq_tail  = (unsigned *)(g_sq_ring + p.sq_off.tail);
    g_sq_mask  = (unsigned *)(g_sq_ring + p.sq_off.ring_mask);
    g_sq_array = (unsigned *)(g_sq_ring + p.sq_off.array);
    g_sq_flags = (unsigned *)(g_sq_ring + p.sq_off.flags);
    g_cq_head  = (unsigned *)(g_cq_ring + p.cq_off.head);
    g_cq_tail  = (unsigned *)(g_cq_ring + p.cq_off.tail);
    g_cq_mask  = (unsigned *)(g_cq_ring + p.cq_off.ring_mask);
    g_cq_overflow = (unsigned *)(g_cq_ring + p.cq_off.overflow);
    g_cqes = (struct io_uring_cqe *)(g_cq_ring + p.cq_off.cqes);

    /* 可选优化：把缓冲池页面一次性注册（钉住），运行期收发不再缺页抖动。
     * 失败不影响正确性（普通地址路径照常工作），故忽略返回值。 */
    {
        struct iovec iov;
        iov.iov_base = g_pool.mem;
        iov.iov_len = (size_t)g_pool.nbufs * g_pool.buflen;
        (void)rosoto_sys_register(g_ring_fd, IORING_REGISTER_BUFFERS, &iov, 1);
    }
    return 0;
}

/* 把积压 SQE 送入内核（只提交、不等待，返回值就是实际消费数，无歧义） */
static void rosoto_ring_flush(void) {
    while (g_sq_unsubmitted > 0) {
        int ret = rosoto_sys_enter(g_ring_fd, g_sq_unsubmitted, 0, 0);
        if (ret > 0) {
            g_sq_unsubmitted -= (unsigned)ret;
            continue;
        }
        if (ret < 0 && errno == EINTR) continue;   /* 信号打断：原样重试 */
        if (ret < 0) { perror("io_uring_enter(submit)"); exit(1); }
        return;   /* ret == 0：环被内核暂时占满，下轮再试 */
    }
}

/* 取一个空闲 SQE；SQ 满时先冲刷再取（保证永远拿得到，不返回 NULL） */
static struct io_uring_sqe *rosoto_sqe(void) {
    for (;;) {
        unsigned tail = *g_sq_tail;   /* tail 只有本线程写 */
        unsigned head = rosoto_load_acq(g_sq_head);
        if (tail - head < g_sq_entries) {
            struct io_uring_sqe *sqe = &g_sqes[tail & *g_sq_mask];
            memset(sqe, 0, sizeof *sqe);
            g_sq_array[tail & *g_sq_mask] = tail & *g_sq_mask;
            rosoto_store_rel(g_sq_tail, tail + 1);
            g_sq_unsubmitted++;
            return sqe;
        }
        rosoto_ring_flush();
    }
}

static int rosoto_cqe_peek(struct io_uring_cqe **out) {
    unsigned head = *g_cq_head;
    if (head == rosoto_load_acq(g_cq_tail)) return 0;
    *out = &g_cqes[head & *g_cq_mask];
    return 1;
}
static void rosoto_cqe_pop(void) {
    rosoto_store_rel(g_cq_head, *g_cq_head + 1);
}

/* ---- 7. SQE 构造：四种操作原语 ---- */
static int  g_lfd = -1;    /* 监听 fd */
static bool g_nodelay;     /* TCP_NODELAY（serve 入参，默认取 ROSOTO_TCP_NODELAY） */

/* ACCEPT：把监听套接字的等待队列交给内核异步收割。
 * addr/addrlen 置 NULL（不需要对端地址，accept 后 getpeername 补齐）；
 * accept_flags=SOCK_NONBLOCK：新 fd 直接非阻塞，免一次 fcntl。 */
static void rosoto_submit_accept(int lfd) {
    struct io_uring_sqe *sqe = rosoto_sqe();
    sqe->opcode = (uint8_t)IORING_OP_ACCEPT;
    sqe->fd = lfd;
    sqe->off = 0;                 /* = addr2 = NULL（不取对端地址） */
    sqe->msg_flags = SOCK_NONBLOCK;   /* union 槽位即 accept_flags */
    sqe->user_data = ROSOTO_UD(0, ROSOTO_OP_ACCEPT, 0);
}

/* RECV：把池缓冲交给内核写入。每连接最多 1 个在飞（rx_bid 占位）。
 * CQE：res>0 收到字节数；res=0 对端 EOF；res<0 错误（含取消）。 */
static void rosoto_submit_recv(RosotoConn *c, uint32_t slot, int32_t bid) {
    struct io_uring_sqe *sqe = rosoto_sqe();
    sqe->opcode = (uint8_t)IORING_OP_RECV;
    sqe->fd = c->fd;
    sqe->addr = (uint64_t)(uintptr_t)rosoto_pool_buf(bid);
    sqe->len = g_pool.buflen;
    sqe->user_data = ROSOTO_UD(c->gen, ROSOTO_OP_RECV, slot);
    c->inflight++;
}

/* SEND：从池缓冲发送 [off, off+len)。MSG_NOSIGNAL 屏蔽 SIGPIPE。
 * CQE：res>0 可能部分完成（流式语义），需续发剩余；res<0 错误/取消。 */
static void rosoto_submit_send(RosotoConn *c, uint32_t slot, int32_t bid, uint32_t off, uint32_t len) {
    struct io_uring_sqe *sqe = rosoto_sqe();
    sqe->opcode = (uint8_t)IORING_OP_SEND;
    sqe->fd = c->fd;
    sqe->addr = (uint64_t)(uintptr_t)(rosoto_pool_buf(bid) + off);
    sqe->len = len;
    sqe->msg_flags = MSG_NOSIGNAL;
    sqe->user_data = ROSOTO_UD(c->gen, ROSOTO_OP_SEND, slot);
    c->inflight++;
}

/* CLOSE：内核异步关 fd。必须等该连接所有在飞 op 的 CQE 都回来
 * （inflight==0）才释放槽位，否则陈旧 CQE 会污染复用后的新连接。 */
static void rosoto_submit_close(RosotoConn *c, uint32_t slot) {
    struct io_uring_sqe *sqe = rosoto_sqe();
    sqe->opcode = (uint8_t)IORING_OP_CLOSE;
    sqe->fd = c->fd;
    sqe->user_data = ROSOTO_UD(c->gen, ROSOTO_OP_CLOSE, slot);
    c->inflight++;
}

/* ---- 8. 应用回调上下文（单线程 reactor：回调期间 g_cur 即当前连接） ---- */
#define NET_ACTION_CLOSE 0
#define NET_ACTION_KEEP  1

static void (*g_on_connect)(int fd);
static int  (*g_on_data)(int fd, const void *buf, size_t n);
static void (*g_on_close)(int fd);

static RosotoConn *g_cur;
static uint32_t   g_cur_slot;
static int        g_cur_owned;   /* 回调是否已接管 recv 缓冲所有权 */

/* 前向声明（调度/收尾互相引用） */
static void rosoto_conn_close(RosotoConn *c, uint32_t slot);
static int  rosoto_conn_enqueue(RosotoConn *c, uint32_t slot, int32_t bid, uint32_t len);
static void rosoto_conn_pump(RosotoConn *c, uint32_t slot);
static void rosoto_conn_arm_recv(RosotoConn *c, uint32_t slot);

/* 零拷贝回写：把 on_data 收到的池缓冲「转移所有权」直接挂入发送队列，
 * 不发生任何 memcpy。buf 必须是 on_data 传入的 recv 缓冲。
 * 返回 NET_ACTION_KEEP；若 close 背压触发断开则返回 NET_ACTION_CLOSE。 */
static int rosoto_conn_echo(const void *buf, size_t n) {
    if (!g_cur || !buf) return NET_ACTION_CLOSE;
    if (n == 0) return NET_ACTION_KEEP;
    if (n > g_pool.buflen) n = g_pool.buflen;   /* recv 上限即池块大小，防御性截断 */
    /* 池内指针 -> 缓冲 id（buf 恒来自 g_pool.mem） */
    int32_t bid = (int32_t)(((const char *)buf - g_pool.mem) / g_pool.buflen);
    if (bid < 0 || (uint32_t)bid >= g_pool.nbufs) return NET_ACTION_CLOSE;
    g_cur_owned = 1;
    return rosoto_conn_enqueue(g_cur, g_cur_slot, bid, (uint32_t)n) < 0
               ? NET_ACTION_CLOSE : NET_ACTION_KEEP;
}

/* 通用发送：拷贝数据入池缓冲后入队（分块，受池容量约束）。
 * 供业务回调主动下发使用；echo 路径请优先 rosoto_conn_echo（零拷贝）。 */
static int rosoto_conn_send(const void *buf, size_t n) {
    if (!g_cur || !buf) return -1;
    const char *p = (const char *)buf;
    size_t off = 0;
    int rc = 0;
    while (off < n) {
        size_t chunk = n - off;
        if (chunk > g_pool.buflen) chunk = g_pool.buflen;
        int32_t bid = rosoto_pool_get();
        if (bid < 0) return -1;   /* 池耗尽：放弃余量（也可按背压策略扩展） */
        memcpy(rosoto_pool_buf(bid), p + off, chunk);
        rc = rosoto_conn_enqueue(g_cur, g_cur_slot, bid, (uint32_t)chunk);
        if (rc < 0) return -1;    /* close 背压已断开 */
        off += chunk;
    }
    return 0;
}

/* ---- 9. 调度：recv 武装（缓冲驱动）+ 发送泵（队列串行） ---- */

/* 为连接武装下一个 RECV。前置条件：ACTIVE、无在飞 RECV、无 block 挂起。
 * 池耗尽时挂入等待链（缓冲释放时由 sched_pump 唤醒）——
 * 此时数据留在内核套接字接收缓冲，TCP 流控自然反压对端，零数据丢失。 */
static void rosoto_conn_arm_recv(RosotoConn *c, uint32_t slot) {
    if (c->state != ROSOTO_ST_ACTIVE) return;
    if (c->rx_bid >= 0 || c->hold_bid >= 0) return;
    int32_t bid = rosoto_pool_get();
    if (bid < 0) { rosoto_wait_push(slot); return; }
    c->rx_bid = bid;
    c->retry = 0;
    rosoto_submit_recv(c, slot, bid);
}

/* 每轮事件循环保证调用一次：把等待链上的连接补上 recv */
static void rosoto_sched_pump(void) {
    while (g_wait_head >= 0 && g_pool.top > 0) {
        int32_t slot = rosoto_wait_pop();
        RosotoConn *c = &g_conns[slot];
        if (c->state != ROSOTO_ST_ACTIVE || c->rx_bid >= 0 || c->hold_bid >= 0) continue;
        rosoto_conn_arm_recv(c, slot);
    }
}

/* 发送队列泵：至多 1 个在飞 SEND（FIFO 头项）。
 * 队列空且有 block 挂起数据时先把挂起数据转正（这就是 block 的重试点）。 */
static void rosoto_conn_pump(RosotoConn *c, uint32_t slot) {
    if (c->state != ROSOTO_ST_ACTIVE) return;
    if (c->send_active) return;
    if (c->sq_head == c->sq_tail) {
        if (c->hold_bid >= 0) {
            int32_t bid = c->hold_bid;
            uint32_t len = c->hold_len;
            c->hold_bid = -1;
            c->hold_len = 0;
            rosoto_conn_enqueue(c, slot, bid, len);   /* 重新走限额判定 */
        }
        rosoto_conn_arm_recv(c, slot);
        return;
    }
    uint8_t h = (uint8_t)(c->sq_head & (ROSOTO_SENDQ_DEPTH - 1));
    c->send_active = 1;
    rosoto_submit_send(c, slot, c->sendq_id[h], c->sendq_off[h], c->sendq_len[h] - c->sendq_off[h]);
}

/* 发送入队 + 背压策略。返回 0 = 已入队或已按策略处理；-1 = 连接已被
 * close 策略断开（调用方应停止使用该连接）。
 * 触发条件：queued_bytes + len 超过 [net] send_buffer，或 FIFO 满。 */
static int rosoto_conn_enqueue(RosotoConn *c, uint32_t slot, int32_t bid, uint32_t len) {
    int full = (c->queued_bytes + len > ROSOTO_SEND_BUF) ||
               ((uint8_t)(c->sq_tail - c->sq_head) >= ROSOTO_SENDQ_DEPTH);
    if (full) {
        switch (ROSOTO_BACKPRESSURE) {
        case ROSOTO_BP_DROP:
            /* drop：丢数据保连接。缓冲立即回池，统计丢弃量。 */
            rosoto_pool_put(bid);
            g_stat_dropped++;
            return 0;
        case ROSOTO_BP_CLOSE:
            /* close：保服务舍连接。归还缓冲并主动断开（fail-fast）。 */
            rosoto_pool_put(bid);
            g_stat_bp_close++;
            rosoto_conn_close(c, slot);
            return -1;
        case ROSOTO_BP_BLOCK:
        default:
            /* block：任务级阻塞重试。数据挂入 hold 槽（不阻塞 reactor），
             * 由发送完成事件驱动补发；期间停武装 recv，TCP 流控反压对端。
             * 理论上 hold 只会有一个（rx 已暂停），防御性回收多余缓冲。 */
            if (c->hold_bid < 0) {
                c->hold_bid = bid;
                c->hold_len = len;
                g_stat_bp_block++;
            } else {
                rosoto_pool_put(bid);
            }
            return 0;
        }
    }
    uint8_t t = (uint8_t)(c->sq_tail & (ROSOTO_SENDQ_DEPTH - 1));
    c->sendq_id[t] = bid;
    c->sendq_len[t] = len;
    c->sendq_off[t] = 0;
    c->sq_tail++;
    c->queued_bytes += len;
    rosoto_conn_pump(c, slot);
    return 0;
}

/* 连接收尾：回收本地资源 -> 应用 on_close -> 提交 IORING_OP_CLOSE。
 * 在飞 RECV/SEND 的缓冲由各自 CQE 回收（内核仍持有引用，不能提前动）。 */
static void rosoto_conn_close(RosotoConn *c, uint32_t slot) {
    if (c->state != ROSOTO_ST_ACTIVE) return;
    c->state = ROSOTO_ST_CLOSING;
    /* 1) block 挂起缓冲立即回池 */
    if (c->hold_bid >= 0) {
        rosoto_pool_put(c->hold_bid);
        c->hold_bid = -1;
        c->hold_len = 0;
    }
    /* 2) 排干发送 FIFO 中「未提交」的项；在飞头项跳过，由 SEND CQE 收尾 */
    {
        uint8_t first = c->sq_head;
        if (c->send_active && first != c->sq_tail) first = (uint8_t)(first + 1);
        while (c->sq_tail != first) {
            uint8_t h = (uint8_t)(c->sq_tail - 1) & (ROSOTO_SENDQ_DEPTH - 1);
            c->sq_tail--;
            rosoto_pool_put(c->sendq_id[h]);
            uint32_t remain = c->sendq_len[h] - c->sendq_off[h];
            if (c->queued_bytes >= remain) c->queued_bytes -= remain;
        }
    }
    /* 3) 应用回调（与 epoll 版一致：先通知再关 fd） */
    if (g_on_close) {
        g_cur = c;
        g_cur_slot = slot;
        g_on_close(c->fd);
        g_cur = NULL;
    }
    /* 4) 提交异步 close；槽位在 inflight 归零时释放 */
    rosoto_submit_close(c, slot);
}

/* 槽位回收判定：close CQE 回来且无其余在飞 op，槽位才可复用 */
static void rosoto_conn_reap(RosotoConn *c, uint32_t slot) {
    if (c->state == ROSOTO_ST_CLOSED && c->inflight == 0) {
        rosoto_slot_free(slot);
        g_nconns--;
    }
}

/* ---- 10. CQE 分发：4 种完成事件的状态机 ---- */
static void rosoto_dispatch(struct io_uring_cqe *cqe) {
    uint64_t ud = cqe->user_data;
    int kind = ROSOTO_UD_KIND(ud);
    uint32_t slot = ROSOTO_UD_SLOT(ud);
    uint32_t gen = ROSOTO_UD_GEN(ud);
    int res = cqe->res;

    if (kind == ROSOTO_OP_ACCEPT) {
        if (res < 0) {
            /* accept 失败（ECONNABORTED/EMFILE/ENOBUFS…）：不停听，继续补位 */
            rosoto_submit_accept(g_lfd);
            return;
        }
        int fd = res;
        int32_t nslot = -1;
        if (g_nconns < g_max_conns) nslot = rosoto_slot_alloc();
        if (nslot < 0) {
            /* fail-fast：超过 [net] max_conns 硬上限，直接关闭新 fd。
             * fd 尚未进 reactor，同步 close(2) 最省事。 */
            g_stat_rejected++;
            close(fd);
            rosoto_submit_accept(g_lfd);
            return;
        }
        RosotoConn *c = &g_conns[nslot];
        c->fd = fd;
        c->state = ROSOTO_ST_ACTIVE;
        c->flags = 0;
        c->rx_bid = -1;
        c->hold_bid = -1;
        c->hold_len = 0;
        c->wait_next = -1;
        c->sq_head = c->sq_tail = 0;
        c->send_active = 0;
        c->retry = 0;
        c->queued_bytes = 0;
        c->inflight = 0;
        if (g_nodelay) {
            int one = 1;
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
        }
        {
            struct sockaddr_in peer;
            socklen_t pl = sizeof peer;
            if (getpeername(fd, (struct sockaddr *)&peer, &pl) == 0) {
                c->peer_ip = peer.sin_addr.s_addr;
                c->peer_port = ntohs(peer.sin_port);
            } else {
                c->peer_ip = 0;
                c->peer_port = 0;
            }
        }
        g_nconns++;
        g_stat_accepted++;
        if (g_on_connect) {
            g_cur = c;
            g_cur_slot = (uint32_t)nslot;
            g_on_connect(fd);
            g_cur = NULL;
        }
        rosoto_conn_arm_recv(c, (uint32_t)nslot);
        rosoto_submit_accept(g_lfd);   /* 监听槽补位，永不停听 */
        return;
    }

    if (slot >= g_nslots) return;               /* 防御 */
    RosotoConn *c = &g_conns[slot];
    if (c->gen != gen) return;                  /* 防御：陈旧 CQE（不应发生） */

    switch (kind) {
    case ROSOTO_OP_RECV: {
        c->inflight--;
        int32_t bid = c->rx_bid;
        c->rx_bid = -1;
        if (res <= 0) {
            if (res == -EAGAIN && c->state == ROSOTO_ST_ACTIVE && c->retry < 64) {
                /* 极端防御：io_uring recv 正常会挂起等待而非 EAGAIN */
                c->retry++;
                c->rx_bid = bid;
                rosoto_submit_recv(c, slot, bid);
                break;
            }
            /* res==0 对端 EOF；res<0 错误/取消 —— 走关闭流程 */
            rosoto_pool_put(bid);
            rosoto_conn_close(c, slot);
            break;
        }
        c->retry = 0;
        if (c->state != ROSOTO_ST_ACTIVE) {
            rosoto_pool_put(bid);   /* 连接已在关闭：不再喂应用 */
            break;
        }
        g_cur = c;
        g_cur_slot = slot;
        g_cur_owned = 0;
        int action = g_on_data ? g_on_data(c->fd, rosoto_pool_buf(bid), (size_t)res)
                               : NET_ACTION_CLOSE;
        if (!g_cur_owned) rosoto_pool_put(bid);   /* 回调未接管缓冲：回收 */
        g_cur = NULL;
        if (action == NET_ACTION_CLOSE) rosoto_conn_close(c, slot);
        else rosoto_conn_arm_recv(c, slot);       /* block 挂起时自动跳过 */
        break;
    }
    case ROSOTO_OP_SEND: {
        c->inflight--;
        c->send_active = 0;
        if (c->sq_head == c->sq_tail) break;      /* 防御：不应发生 */
        uint8_t h = (uint8_t)(c->sq_head & (ROSOTO_SENDQ_DEPTH - 1));
        uint32_t remain = c->sendq_len[h] - c->sendq_off[h];
        if (res > 0) {
            c->sendq_off[h] += (uint32_t)res;     /* 流式 SEND 可能部分完成 */
            if (c->queued_bytes >= (uint32_t)res) c->queued_bytes -= (uint32_t)res;
            remain -= (uint32_t)res;
            c->retry = 0;
        }
        if (res < 0 && res != -EAGAIN) {
            /* 发送错误：回收缓冲、丢弃该项、断开连接 */
            rosoto_pool_put(c->sendq_id[h]);
            if (c->queued_bytes >= remain) c->queued_bytes -= remain;
            c->sq_head++;
            rosoto_conn_close(c, slot);
            break;
        }
        if (remain == 0) {
            rosoto_pool_put(c->sendq_id[h]);      /* 整块发完：缓冲回池 */
            c->sq_head++;
        } else if (res == -EAGAIN) {
            if (++c->retry > 64) {
                rosoto_pool_put(c->sendq_id[h]);
                c->sq_head++;
                rosoto_conn_close(c, slot);
                break;
            }
        }
        if (c->state == ROSOTO_ST_ACTIVE) {
            rosoto_conn_pump(c, slot);            /* 续发剩余/下一挂起项 */
        } else {
            /* CLOSING：close 已排干未提交项，这里只需处理在飞项残留 */
            while (c->sq_head != c->sq_tail) {
                uint8_t hh = (uint8_t)(c->sq_head & (ROSOTO_SENDQ_DEPTH - 1));
                rosoto_pool_put(c->sendq_id[hh]);
                c->sq_head++;
            }
        }
        break;
    }
    case ROSOTO_OP_CLOSE:
        c->inflight--;
        c->fd = -1;
        c->state = ROSOTO_ST_CLOSED;
        break;
    default:
        break;
    }
    rosoto_conn_reap(c, slot);
}

/* ---- 11. reactor 主循环 ---- */
/* 提交与等待分离，避免 io_uring_enter 的部分提交/信号歧义：
 *   A. 提交积压 SQE（min_complete=0，返回值即消费数）
 *   B. 非阻塞收割全部 CQE 并分发
 *   C. 无 CQE 时阻塞等待至少 1 个（EINTR 由信号处理置 g_stop 后收尾退出） */
static volatile sig_atomic_t g_stop;

static void rosoto_on_signal(int sig) {
    (void)sig;
    g_stop = 1;
}

static void rosoto_reactor_loop(void) {
    for (;;) {
        if (g_stop) return;
        rosoto_sched_pump();               /* 缓冲释放 -> 唤醒等待者 */
        rosoto_ring_flush();               /* A. 提交积压 SQE */
        struct io_uring_cqe *cqe;
        int got = 0;
        while (rosoto_cqe_peek(&cqe)) {    /* B. 收割 + 分发 */
            rosoto_dispatch(cqe);
            rosoto_cqe_pop();
            got++;
        }
        if (got == 0) {
            /* C. 无事可做：阻塞等第一个 CQE（监听 accept 恒在飞，不会饿死） */
            int ret = rosoto_sys_enter(g_ring_fd, 0, 1, IORING_ENTER_GETEVENTS);
            if (ret < 0 && errno != EINTR) {
                perror("io_uring_enter(wait)");
                exit(1);
            }
            while (rosoto_cqe_peek(&cqe)) {
                rosoto_dispatch(cqe);
                rosoto_cqe_pop();
            }
        }
        if (*g_cq_overflow) {
            /* FEAT_NODROP 内核不会丢 CQE，但会标记溢出；等待路径会顺带冲刷 */
            fprintf(stderr, "[rosoto-uring] warning: CQ overflow, flushing\n");
            *g_cq_overflow = 0;
        }
    }
}

/* ---- 12. 服务入口（签名与 epoll 版 rosoto_echo_serve 对应） ---- */
static void rosoto_uring_serve(const char *addr,
                               void (*on_connect)(int fd),
                               int (*on_data)(int fd, const void *buf, size_t n),
                               void (*on_close)(int fd),
                               int64_t max_conns, int64_t backlog,
                               bool nodelay, bool reuse_port) {
    g_on_connect = on_connect;
    g_on_data = on_data;
    g_on_close = on_close;
    g_nodelay = nodelay;

    /* 解析 addr: host:port */
    char host[128] = "0.0.0.0";
    int port = 0;
    const char *colon = strrchr(addr, ':');
    if (colon) {
        size_t hl = (size_t)(colon - addr);
        if (hl >= sizeof host) hl = sizeof host - 1;
        memcpy(host, addr, hl);
        host[hl] = 0;
        port = atoi(colon + 1);
    }

    /* 监听套接字（创建后所有数据 IO 都走 io_uring） */
    g_lfd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    if (g_lfd < 0) { perror("socket"); exit(1); }
    int one = 1;
    setsockopt(g_lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (reuse_port) setsockopt(g_lfd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof one);
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons((uint16_t)port);
    sa.sin_addr.s_addr = strcmp(host, "0.0.0.0") == 0 ? INADDR_ANY : inet_addr(host);
    if (bind(g_lfd, (struct sockaddr *)&sa, sizeof sa) < 0) { perror("bind"); exit(1); }
    if (listen(g_lfd, backlog > 0 ? (int)backlog : ROSOTO_BACKLOG) < 0) { perror("listen"); exit(1); }

    /* io_uring 实例：内核未启用/被 seccomp 拦截时优雅退出（约定退出码 42），
     * 由构建脚本据此跳过回环测试而不是误报失败。 */
    if (rosoto_ring_init(ROSOTO_RING_ENTRIES) < 0) {
        fprintf(stderr, "ROSOTO_URING_UNAVAILABLE: %s\n", strerror(errno));
        exit(42);
    }

    /* 连接表 + 空闲栈：一次性分配，之后每连接零 malloc */
    g_max_conns = (uint64_t)max_conns;
    if (g_max_conns > (uint64_t)ROSOTO_NET_MAX_CONNS) g_max_conns = (uint64_t)ROSOTO_NET_MAX_CONNS;
    g_nslots = (uint32_t)g_max_conns;
    g_conns = (RosotoConn *)calloc(g_nslots, sizeof(RosotoConn));
    g_free_slots = (uint32_t *)malloc((size_t)g_nslots * sizeof(uint32_t));
    if (!g_conns || !g_free_slots) { perror("calloc conns"); exit(1); }
    for (uint32_t i = 0; i < g_nslots; i++) {
        g_conns[i].fd = -1;
        g_conns[i].rx_bid = -1;
        g_conns[i].hold_bid = -1;
        g_conns[i].wait_next = -1;
        g_free_slots[i] = g_nslots - 1 - i;
    }
    g_free_top = g_nslots;

    /* 缓冲池（recv/send 共用） */
    if (rosoto_pool_init(ROSOTO_POOL_BUFS, ROSOTO_RECV_BUF) < 0) {
        perror("pool init");
        exit(1);
    }

    /* 信号：优雅退出（sigaction 不带 SA_RESTART，保证等待可被 EINTR 打断） */
    struct sigaction sa_sig;
    memset(&sa_sig, 0, sizeof sa_sig);
    sa_sig.sa_handler = rosoto_on_signal;
    sigaction(SIGINT, &sa_sig, NULL);
    sigaction(SIGTERM, &sa_sig, NULL);
    signal(SIGPIPE, SIG_IGN);   /* 双保险：SEND 已带 MSG_NOSIGNAL */

    /* 首发 ACCEPT，进入事件循环 */
    rosoto_submit_accept(g_lfd);
    printf("ROSOTO_URING_READY %s:%d\n", host, port);
    fflush(stdout);
    rosoto_reactor_loop();

    /* 优雅收尾：打印统计（供测试/运维核对 fail-fast 与背压行为） */
    fprintf(stderr,
            "[rosoto-uring] shutdown: accepted=%llu rejected=%llu dropped=%llu bp_close=%llu bp_block=%llu\n",
            (unsigned long long)g_stat_accepted,
            (unsigned long long)g_stat_rejected,
            (unsigned long long)g_stat_dropped,
            (unsigned long long)g_stat_bp_close,
            (unsigned long long)g_stat_bp_block);
}

/* ---- 13. 应用层回调：默认 echo（签名与 epoll 版一致，可整体替换） ---- */
static void on_connect(int fd) {
    /* echo 应用无需连接级初始化；业务可在此挂状态 */
    (void)fd;
}

static int on_data(int fd, const void *buf, size_t n) {
    /* echo：原样回显。零拷贝 —— 转移 recv 缓冲所有权到发送队列。 */
    (void)fd;
    return rosoto_conn_echo(buf, n);
}

static void on_close(int fd) {
    (void)fd;
}

/* ---- 14. main：`./rt [host:port]`（缺省 127.0.0.1:7777 或 $ROSOTO_ADDR） ---- */
int main(int argc, char **argv) {
    const char *addr = getenv("ROSOTO_ADDR");
    if (argc > 1 && strcmp(argv[1], "--help") == 0) {
        fprintf(stderr, "usage: %s [host:port]   (default 127.0.0.1:7777)\n", argv[0]);
        return 0;
    }
    if (argc > 1) addr = argv[1];
    if (!addr || !*addr) addr = "127.0.0.1:7777";

    rosoto_uring_serve(addr, on_connect, on_data, on_close,
                       ROSOTO_NET_MAX_CONNS, ROSOTO_BACKLOG,
                       ROSOTO_TCP_NODELAY != 0, ROSOTO_REUSE_PORT != 0);
    return 0;
}
"""

# ---------------------------------------------------------------------------
# 3. 命令行入口
# ---------------------------------------------------------------------------

def _build_arg_parser():
    p = argparse.ArgumentParser(
        prog="rosoto_uring.py",
        description="发射 Rosoto io_uring 网络后端 C 运行时（自包含，无 liburing）",
    )
    p.add_argument("--max-conns", type=int, default=None,
                   help="连接硬上限（默认 %d）" % DEFAULT_NET["max_conns"])
    p.add_argument("--backpressure", choices=sorted(BACKPRESSURE_CODES),
                   default=None, help="背压策略（默认 %s）" % DEFAULT_NET["backpressure"])
    p.add_argument("--recv-buffer", type=int, default=None,
                   help="池缓冲块字节数（默认 %d）" % DEFAULT_NET["recv_buffer"])
    p.add_argument("--send-buffer", type=int, default=None,
                   help="每连接发送限额字节数（默认 %d）" % DEFAULT_NET["send_buffer"])
    p.add_argument("--backlog", type=int, default=None,
                   help="listen backlog（默认 %d）" % DEFAULT_NET["backlog"])
    p.add_argument("--pool-buffers", type=int, default=None,
                   help="缓冲池块数（默认 %d）" % DEFAULT_NET["pool_buffers"])
    p.add_argument("--ring-entries", type=int, default=None,
                   help="SQE 环深度（默认 %d）" % DEFAULT_NET["ring_entries"])
    p.add_argument("--tcp-nodelay", dest="tcp_nodelay", type=_as_bool, default=None,
                   metavar="BOOL", help="TCP_NODELAY（默认 true）")
    p.add_argument("--reuse-port", dest="reuse_port", type=_as_bool, default=None,
                   metavar="BOOL", help="SO_REUSEPORT（默认 true）")
    return p


def main(argv=None):
    """命令行入口：`python3 tools/rosoto_uring.py emit [...]`，C 源码打到 stdout。"""
    args = list(sys.argv[1:] if argv is None else argv)
    # 兼容 `emit` 子命令与直接传参数两种写法
    if args and args[0] == "emit":
        args = args[1:]
    elif args and not args[0].startswith("-"):
        sys.stderr.write("rosoto_uring.py: 未知子命令 %r（仅支持 emit）\n" % args[0])
        return 2

    ns = _build_arg_parser().parse_args(args)
    net = dict(DEFAULT_NET)
    for key in ("max_conns", "backpressure", "recv_buffer", "send_buffer",
                "backlog", "pool_buffers", "ring_entries", "tcp_nodelay", "reuse_port"):
        val = getattr(ns, key)
        if val is not None:
            net[key] = val
    try:
        c_src = emit_uring_runtime({"net": net})
    except ValueError as e:
        sys.stderr.write("rosoto_uring.py: %s\n" % e)
        return 2
    sys.stdout.write(c_src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
