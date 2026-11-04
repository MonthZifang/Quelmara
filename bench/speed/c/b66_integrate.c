// b66_integrate
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

static int64_t f(int64_t x) { return (x*x + 3*x + 5) % 1000003; }
int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 1000000; i++) acc = (acc + f(i)) % 1000003;
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
