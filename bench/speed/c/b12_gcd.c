// b12_gcd —— GCD 密集：3000 万次辗转相除
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "bench.h"

static int64_t gcd(int64_t a, int64_t b) {
    while (b) { int64_t t = b; b = a % b; a = t; }
    return a;
}
int main(void) {
    int64_t n = 30000000;
    T0();
    int64_t s = 0;
    for (int64_t i = 1; i <= n; i++) s += gcd(i, 1000000 - i);
    printf("%lld\n", (long long)s);
    T1();
    TPRINT();
    return 0;
}
