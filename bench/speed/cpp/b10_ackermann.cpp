// b10_ackermann —— Ackermann(2,8)：深层非原始递归
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "bench.h"

static int64_t ack(int64_t m, int64_t n) {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}
int main(void) {
    T0();
    int64_t r = ack(2, 8);
    printf("%lld\n", (long long)r);
    T1();
    TPRINT();
    return 0;
}
