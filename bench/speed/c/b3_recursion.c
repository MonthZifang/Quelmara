// b3_recursion —— 朴素递归 fib(30)
#include <stdio.h>
#include <stdint.h>
#include "bench.h"


static int64_t fib(int64_t n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

int main(void) {
    T0();
    printf("%lld\n", (long long)fib(30));
    T1();
    TPRINT();
    return 0;
}
