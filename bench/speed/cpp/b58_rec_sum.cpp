// b58_rec_sum
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

// v4.115 fairness audit: per-level empty-asm barrier stops compile-time
// evaluation / closed-form replacement of the recursion (zero instructions).
static int64_t rec_sum(int64_t n) {
    if (n <= 0) return 0;
    int64_t r = n + rec_sum(n - 1);
    __asm__ volatile("" : "+r"(r) :: "memory");
    return r;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 1; i <= 100; i++) acc += rec_sum(10000);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
