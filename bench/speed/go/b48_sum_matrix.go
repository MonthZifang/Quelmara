// b48_sum_matrix —— 500×500 矩阵按行求和再累加
package main

import (
	"fmt"
)

func main() {
	n := int64(500)
	sz := n * n
	a := make([]int64, sz)
	for i := int64(0); i < sz; i++ {
		a[i] = i
	}
	t0 := benchNow()
	var total int64 = 0
	for r := int64(0); r < n; r++ {
		var s int64 = 0
		for c := int64(0); c < n; c++ {
			s += a[r*n+c]
		}
		total += s
	}
	el := benchElapsed(t0)
	fmt.Println(total)
	fmt.Println("T")
	fmt.Println(el)
}
