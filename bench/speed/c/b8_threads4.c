// b8_threads4 —— 同样 4000 万次总量，拆成 4 个线程
#include <stdio.h>
#include <stdint.h>
#include <windows.h>

static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); } while (0)


typedef struct { int64_t n; int64_t r; } Job;

static DWORD WINAPI run(LPVOID p) {
    Job *j = (Job *)p;
    int64_t acc = 0;
    for (int64_t i = 0; i < j->n; i++) acc += (i * 7) % 13;
    j->r = acc;
    return 0;
}

int main(void) {
    T0();
    Job jobs[4];
    HANDLE th[4];
    for (int k = 0; k < 4; k++) {
        jobs[k].n = 40000000;
        jobs[k].r = 0;
        th[k] = CreateThread(NULL, 0, run, &jobs[k], 0, NULL);
    }
    WaitForMultipleObjects(4, th, TRUE, INFINITE);
    for (int k = 0; k < 4; k++) CloseHandle(th[k]);
    printf("%lld\n", (long long)(jobs[0].r + jobs[1].r + jobs[2].r + jobs[3].r));
    T1();
    TPRINT();
    return 0;
}
