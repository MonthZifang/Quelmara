// b42_matrix_transpose —— 500×500 矩阵转置
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(500)
	sz := n * n
	a := make([]int64, sz)
	for i := int64(0); i < sz; i++ {
		a[i] = i
	}
	b := make([]int64, sz)
	t0 := time.Now()
	for r := int64(0); r < n; r++ {
		for c := int64(0); c < n; c++ {
			b[r*n+c] = a[c*n+r]
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(b[sz-1])
	fmt.Println("T")
	fmt.Println(el)
}
