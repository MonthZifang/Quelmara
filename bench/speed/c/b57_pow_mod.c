// b57_pow_mod
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t pow_mod(int64_t base, int64_t exp, int64_t mod) {
    int64_t result = 1, b = base % mod;
    while (exp > 0) {
        if (exp % 2 == 1) result = (result * b) % mod;
        b = (b * b) % mod; exp /= 2;
    }
    return result;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 1; i <= 1000000; i++) acc = (acc + pow_mod(i, i, 1000003)) % 1000003;
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
