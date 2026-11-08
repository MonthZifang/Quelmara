// b44_stack_sim
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t *st =(int64_t*)malloc(1000000 * 8);
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
