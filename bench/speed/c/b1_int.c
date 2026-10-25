// b1_int —— 整数运算热循环，20M 次
#include <stdio.h>
#include <stdint.h>
#include <windows.h>

static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); } while (0)


int main(void) {
    T0();
    int64_t n = 20000000, acc = 0;
    for (int64_t i = 0; i < n; i++) acc += (i * 7) % 13;
    printf("%lld\n", (long long)acc);
    T1();
    TPRINT();
    return 0;
}
