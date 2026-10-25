// b5_string —— 20 万次 int→str→int
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); } while (0)


int main(void) {
    T0();
    int64_t n = 500000, acc = 0;
    char buf[24];
    for (int64_t i = 0; i < n; i++) {
        int len = snprintf(buf, sizeof buf, "%lld", (long long)i);
        acc += len;
        acc += (int64_t)strtoll(buf, NULL, 10);
    }
    printf("%lld\n", (long long)acc);
    T1();
    TPRINT();
    return 0;
}
