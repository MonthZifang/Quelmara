// b43_gcd_lcm
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

static int64_t gcd(int64_t a, int64_t b) {
    while (b) { int64_t t = b; b = a % b; a = t; }
    return a;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 1; i <= 1000000; i++) acc += gcd(i, 1000000 - i + 1);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
