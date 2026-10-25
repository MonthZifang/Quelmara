// b4_array —— 数组写入 + 顺序遍历 + 跨步遍历（200 万元素）
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <windows.h>

static LARGE_INTEGER _f, _a, _b;
#define T0() do { QueryPerformanceFrequency(&_f); QueryPerformanceCounter(&_a); } while (0)
#define T1() do { QueryPerformanceCounter(&_b); } while (0)
#define TPRINT() do { printf("T\n%lld\n", (long long)((_b.QuadPart - _a.QuadPart) * 1000000000LL / _f.QuadPart)); } while (0)


int main(void) {
    T0();
    int64_t n = 2000000;
    int64_t *v = (int64_t *)malloc((size_t)n * 8);
    for (int64_t i = 0; i < n; i++) v[i] = i * 3 + 1;
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += v[i];
    int64_t t = 0;
    for (int64_t i = 0; i < n; i += 7) t += v[i];
    printf("%lld\n", (long long)s);
    printf("%lld\n", (long long)t);
    free(v);
    T1();
    TPRINT();
    return 0;
}
