// b46_strcat
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    T0();
    int64_t acc = 0;
    for (int64_t i = 0; i < 100000; i++) {
        char s[64];
        int n = snprintf(s, 64, "%s %s %s", "hello", "world", "12345");
        acc += n;
    }
    T1();
    printf("%lld\n", (long long)acc);
    TPRINT();
    return 0;
}
