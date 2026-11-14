// b53_thread_sim
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

// v4.115 fairness audit: per-iteration empty-asm barrier stops closed-form
// replacement of the sum (zero instructions emitted, algorithm unchanged).
static int64_t work(int64_t start, int64_t end) {
    int64_t s = 0;
    for (int64_t i = start; i < end; i++) {
        s += i * 2 + 1;
        __asm__ volatile("" : "+r"(s) :: "memory");
    }
    return s;
}
int main(void) {
    int64_t n = 10000000;
    T0();
    int64_t a = work(0, n/4), b = work(n/4, n/2);
    int64_t c = work(n/2, 3*n/4), d = work(3*n/4, n);
    T1();
    printf("%lld\n", (long long)(a+b+c+d));
    TPRINT();
    return 0;
}
