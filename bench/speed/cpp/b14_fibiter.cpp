// b14_fibiter —— 迭代 fib(5000 万)：纯循环 vs 递归对照
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "bench.h"

int main(void) {
    int64_t n = 50000000;
    T0();
    int64_t a = 0, b = 1;
    for (int64_t i = 0; i < n; i++) {
        int64_t t = a + b;
        a = b;
        b = t % 1000000007;
    }
    T1();
    printf("%lld\n", (long long)a);
    TPRINT();
    return 0;
}
