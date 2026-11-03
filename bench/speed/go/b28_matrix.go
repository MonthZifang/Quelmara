// b28_matrix —— 矩阵乘法 300×300（朴素三重循环）
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(300)
	a := make([]int64, n*n)
	b := make([]int64, n*n)
	c := make([]int64, n*n)
	seed := uint64(7)
	for i := int64(0); i < n*n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 100)
		seed = (seed*1103515245 + 12345) % 2147483648
		b[i] = int64(seed % 100)
	}
	t0 := time.Now()
	for r := int64(0); r < n; r++ {
		for k := int64(0); k < n; k++ {
			av := a[r*n+k]
			for j := int64(0); j < n; j++ { c[r*n+j] += av * b[k*n+j] }
		}
	}
	el := time.Since(t0).Nanoseconds()
	var chk int64
	for i := int64(0); i < n*n; i++ { chk = (chk + c[i]) % 1000000007 }
	fmt.Println(chk)
	fmt.Println("T")
	fmt.Println(el)
}
