// b44_stack_sim
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t *st = malloc(1000000 * 8);
    int64_t top = 0;
    T0();
    for (int64_t i = 0; i < 1000000; i++) {
        st[top++] = i;
        if (i % 3 == 0 && top > 0) st[top-1]++;
    }
    T1();
    printf("%lld\n", (long long)st[top-1]);
    TPRINT();
    free(st);
    return 0;
}
