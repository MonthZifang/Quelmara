// b35_branch
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t acc = 0;
    T0();
    for (int64_t i = 0; i < 20000000; i++) {
        if ((i & 3) == 0) acc += 1; else acc -= 1;
    }
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
