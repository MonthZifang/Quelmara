// b71_sum_squares
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

// v4.115 fairness audit: per-iteration empty-asm barrier stops closed-form
// replacement of the sum (zero instructions emitted, algorithm unchanged).
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 1; i <= 1000000; i++) {
        acc += i * i;
        __asm__ volatile("" : "+r"(acc) :: "memory");
    }
    T1();
    printf("%lld\n", (long long)(acc % 1000003));
    TPRINT();
    return 0;
}
