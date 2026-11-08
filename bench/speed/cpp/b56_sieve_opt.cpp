// b56_sieve_opt
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 2000000;
    int64_t *flags =(int64_t*)malloc((n+1) * 8);
    for (int64_t i = 0; i <= n; i++) flags[i] = 1;
    flags[0] = flags[1] = 0;
    T0();
    for (int64_t p = 2; p * p <= n; p++)
        if (flags[p]) for (int64_t q = p*p; q <= n; q += p) flags[q] = 0;
    int64_t cnt = 0;
    for (int64_t k = 2; k <= n; k++) if (flags[k]) cnt++;
    T1();
    printf("%lld\n", (long long)cnt);
    TPRINT();
    free(flags);
    return 0;
}
