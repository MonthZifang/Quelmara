// b38_prime
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int is_prime(int64_t n) {
    if (n < 2) return 0;
    if (n == 2) return 1;
    if (n % 2 == 0) return 0;
    for (int64_t d = 3; d * d <= n; d += 2)
        if (n % d == 0) return 0;
    return 1;
}
int main(void) {
    int64_t cnt = 0;
    T0();
    for (int64_t i = 0; i < 100000; i++) if (is_prime(i)) cnt++;
    T1();
    printf("%lld\n", (long long)cnt);
    TPRINT();
    return 0;
}
