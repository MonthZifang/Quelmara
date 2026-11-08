// b62_pred_branch
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 5000000; i++) {
        if ((i * 7 + 3) % 5 < 2) acc += 1; else acc -= 1;
    }
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
