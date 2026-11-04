// b77_rec_fib
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t fib(int64_t n) {
    if (n <= 1) return n;
    return fib(n-1) + fib(n-2);
}
int main(void) {
    T0();
    int64_t r = fib(25);
    T1();
    printf("%lld\n", (long long)r);
    TPRINT();
    return 0;
}
