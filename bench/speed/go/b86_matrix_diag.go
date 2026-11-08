// b86_matrix_diag —— 1000×1000 矩阵对角线求和
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000)
	sz := n * n
	a := make([]int64, sz)
	for i := int64(0); i < sz; i++ {
		a[i] = (i*7 + 3) % 100
	}
	t0 := time.Now()
	var sum int64 = 0
	for r := int64(0); r < n; r++ {
		sum += a[r*n+r]
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(sum)
	fmt.Println("T")
	fmt.Println(el)
}
