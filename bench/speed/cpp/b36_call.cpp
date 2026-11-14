// b36_call
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

// v4.115 fairness audit: without a barrier the whole loop is eliminated --
// GCC folds constant bounds at compile time, clang (zig cc) even replaces
// runtime-bound sums by a closed form. The empty asm emits zero instructions
// and only makes the result opaque; algorithm and checksum are unchanged.
static int64_t add3(int64_t a, int64_t b, int64_t c) {
    int64_t r = a + b + c;
    __asm__ volatile("" : "+r"(r) :: "memory");
    return r;
}
int main(void) {
    int64_t acc = 0;
    T0();
    for (int64_t i = 0; i < 10000000; i++) acc = add3(acc, i, 1);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
