// b33_startup
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int64_t init(void) {
    int64_t s = 0;
    for (int64_t i = 0; i < 1000; i++) s += i;
    return s;
}
int main(void) {
    T0();
    int64_t a = init(), b = init(), c = init(), d = init();
    T1();
    printf("%lld\n", (long long)(a+b+c+d));
    TPRINT();
    return 0;
}
