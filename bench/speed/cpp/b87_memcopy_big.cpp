// b87_memcopy_big
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <chrono>
#include <cstring>

static int64_t now_ns(void) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(void) {
    size_t n = 12500000;
    int64_t *src =(int64_t*)malloc(n * 8);
    int64_t *dst =(int64_t*)malloc(n * 8);
    for (size_t i = 0; i < n; i++) src[i] = (int64_t)i * 7 + 1;
    int64_t t0 = now_ns();
    memcpy(dst, src, n * 8);
    int64_t t1 = now_ns();
    int64_t chk = dst[0] + dst[6250000] + dst[n - 1];
    printf("%lld\nT\n%lld\n", (long long)chk, (long long)(t1 - t0));
    return 0;
}
