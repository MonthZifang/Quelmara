// b8_threads4 —— 同样 4000 万次总量，拆成 4 个线程
#include <stdio.h>
#include <stdint.h>
#include "bench.h"


typedef struct { int64_t n; int64_t r; } Job;

// v2.54：Windows 用 CreateThread，POSIX 用 pthread —— 同一道题、同一种线程模型
// （4 个可 join 的 OS 线程，无池、无复用），保证跨平台可比。
#ifdef _WIN32
static DWORD WINAPI run(LPVOID p) {
    Job *j = (Job *)p;
    int64_t acc = 0;
    for (int64_t i = 0; i < j->n; i++) acc += (i * 7) % 13;
    j->r = acc;
    return 0;
}
#else
static void *run(void *p) {
    Job *j = (Job *)p;
    int64_t acc = 0;
    for (int64_t i = 0; i < j->n; i++) acc += (i * 7) % 13;
    j->r = acc;
    return NULL;
}
#endif

int main(void) {
    T0();
    Job jobs[4];
    bench_thread th[4];
    for (int k = 0; k < 4; k++) {
        jobs[k].n = 40000000;
        jobs[k].r = 0;
#ifdef _WIN32
        th[k] = CreateThread(NULL, 0, run, &jobs[k], 0, NULL);
#else
        pthread_create(&th[k], NULL, run, &jobs[k]);
#endif
    }
#ifdef _WIN32
    WaitForMultipleObjects(4, th, TRUE, INFINITE);
    for (int k = 0; k < 4; k++) CloseHandle(th[k]);
#else
    for (int k = 0; k < 4; k++) pthread_join(th[k], NULL);
#endif
    printf("%lld\n", (long long)(jobs[0].r + jobs[1].r + jobs[2].r + jobs[3].r));
    T1();
    TPRINT();
    return 0;
}
