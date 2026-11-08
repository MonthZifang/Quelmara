// b70_lin_search
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include "bench.h"

int main(void) {
    int64_t n = 1000;
    int64_t *a =(int64_t*)malloc(n * 8);
    for (int64_t i = 0; i < n; i++) a[i] = i * 3 + 7;
    T0();
    int64_t found = 0;
    for (int64_t j = 0; j < 1000000; j++) {
        int64_t target = (j * 37 + 11) % 3000;
        for (int64_t k = 0; k < n; k++) if (a[k] == target) found++;
    }
    T1();
    printf("%lld\n", (long long)found);
    TPRINT();
    free(a);
    return 0;
}
