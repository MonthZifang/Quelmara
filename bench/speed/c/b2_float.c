// b2_float —— 浮点运算：调和级数前 5M 项
#include <stdio.h>
#include <stdint.h>
#include <windows.h>

static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); } while (0)


int main(void) {
    T0();
    int64_t n = 5000000;
    double acc = 0.0;
    for (int64_t i = 1; i <= n; i++) acc += 1.0 / (double)i;
    printf("%.6f\n", acc);
    T1();
    TPRINT();
    return 0;
}
