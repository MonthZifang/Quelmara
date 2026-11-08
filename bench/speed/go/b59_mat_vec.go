// b59_mat_vec —— 矩阵-向量乘累加：500×500
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(500)
	sz := n * n
	mat := make([]int64, sz)
	vec := make([]int64, n)
	for i := int64(0); i < sz; i++ {
		mat[i] = (i*7 + 3) % 100
	}
	for j := int64(0); j < n; j++ {
		vec[j] = (j*13 + 1) % 100
	}
	t0 := time.Now()
	var total int64 = 0
	for r := int64(0); r < n; r++ {
		var s int64 = 0
		for c := int64(0); c < n; c++ {
			s += mat[r*n+c] * vec[c]
		}
		total += s
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(total)
	fmt.Println("T")
	fmt.Println(el)
}
