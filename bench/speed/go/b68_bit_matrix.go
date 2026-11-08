// b68_bit_matrix —— 256×256 比特矩阵转置式写入
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(256)
	sz := n * n
	a := make([]int64, sz)
	for i := int64(0); i < sz; i++ {
		a[i] = i % 2
	}
	b := make([]int64, sz)
	t0 := time.Now()
	for r := int64(0); r < n; r++ {
		for c := int64(0); c < n; c++ {
			b[r*n+c] = a[c*n+(n-1-r)]
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(b[0])
	fmt.Println("T")
	fmt.Println(el)
}
