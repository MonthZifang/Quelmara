// b15_loopsum —— 最朴素循环累加 2 亿次（循环开销基线）
//
// **不能让它被优化掉**：单纯 `s += i` 在 -O2 下会被 GCC/Clang 折叠成闭式解
// （实测 C 只要 0.1 ms，而 qlmc 要 264 ms —— 那不是语言差距，是基准写错了）。
// 做法：每轮把 `s` 和 `i` 做一次依赖，让编译器无法提前算出结果。
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include "bench.h"

int main(void) {
    int64_t n = 200000000;
    T0();
    volatile int64_t s = 0;
    int64_t x = 1;
    for (int64_t i = 0; i < n; i++) {
        x = (x * 31 + i) | 1;      // 依赖链：不能折叠
        s = (int64_t)s + (x & 1023);
    }
    printf("%lld\n", (long long)s);
    T1();
    TPRINT();
    return 0;
}
