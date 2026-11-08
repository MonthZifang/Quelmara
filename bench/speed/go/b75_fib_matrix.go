// b75_fib_matrix —— 矩阵快速幂求斐波那契（n=1000）
package main

import (
	"fmt"
	"time"
)

func main() {
	a0, a1, a2, a3 := int64(1), int64(1), int64(1), int64(0)
	n := int64(1000)
	t0 := time.Now()
	for n > 0 {
		if n%2 == 1 {
			t := (a0*a1 + a1*a3) % 1000003
			u := (a0*a2 + a1*a3) % 1000003
			v := (a2*a1 + a3*a3) % 1000003
			w := (a2*a1 + a3*a3) % 1000003
			a0, a1, a2, a3 = t, u, v, w
		}
		b0 := (a0*a0 + a1*a2) % 1000003
		b1 := (a0*a1 + a1*a3) % 1000003
		b2 := (a2*a0 + a3*a2) % 1000003
		b3 := (a2*a1 + a3*a3) % 1000003
		a0, a1, a2, a3 = b0, b1, b2, b3
		n /= 2
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a1)
	fmt.Println("T")
	fmt.Println(el)
}
