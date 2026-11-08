// b78_sum_digits
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

static int64_t digit_sum(int64_t n) {
    int64_t s = 0;
    while (n > 0) { s += n % 10; n /= 10; }
    return s;
}
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 1000000; i++) acc += digit_sum(i);
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
