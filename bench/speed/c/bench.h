// bench.h —— 四语言基准的跨平台薄封装（v2.54）
//
// 只做两件事：① 单调时钟（Windows 用 QPC，POSIX 用 CLOCK_MONOTONIC）；
// ② 给 b8_threads4 用的线程句柄类型。
//
// **为什么不在每个 .c 里重复一遍**：原来 10 个文件各自内联一份 QPC 宏，
// 想加 POSIX 支持就要改 10 处 —— 集中到一个头文件只改一处。
//
// 计时口径：只圈住负载，不圈进程创建。本机 `CreateProcess` 要 447 ms，
// 用挂钟量等于量进程创建（见 RESULTS.md）。
#ifndef BENCH_H
#define BENCH_H

#include <stdio.h>
#include <stdint.h>

#ifdef _WIN32

#include <windows.h>
static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { \
    printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); \
} while (0)
typedef HANDLE bench_thread;

#else

#include <time.h>
#include <pthread.h>
static struct timespec _a, _b;
#define T0() do { clock_gettime(CLOCK_MONOTONIC, &_a); } while (0)
#define T1() do { clock_gettime(CLOCK_MONOTONIC, &_b); } while (0)
#define TPRINT() do { \
    long long _ns = (long long)(_b.tv_sec - _a.tv_sec) * 1000000000LL \
                    + ((long long)_b.tv_nsec - (long long)_a.tv_nsec); \
    printf("T\n%lld\n", _ns); \
} while (0)
typedef pthread_t bench_thread;

#endif

#endif
