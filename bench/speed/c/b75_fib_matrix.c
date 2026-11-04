// b75_fib_matrix
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    T0();
    int64_t a0=1,a1=1,a2=1,a3=0;
    int64_t n = 1000;
    while (n > 0) {
        if (n % 2 == 1) {
            int64_t t=(a0*a1+a1*a3)%1000003,u=(a0*a2+a1*a3)%1000003;
            int64_t v=(a2*a1+a3*a3)%1000003,w=(a2*a1+a3*a3)%1000003;
            a0=t;a1=u;a2=v;a3=w;
        }
        int64_t b0=(a0*a0+a1*a2)%1000003,b1=(a0*a1+a1*a3)%1000003;
        int64_t b2=(a2*a0+a3*a2)%1000003,b3=(a2*a1+a3*a3)%1000003;
        a0=b0;a1=b1;a2=b2;a3=b3;
        n /= 2;
    }
    T1();
    printf("%lld\n", (long long)a1);
    TPRINT();
    return 0;
}
