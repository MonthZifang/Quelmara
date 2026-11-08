// b37_swap —— 冒泡式相邻交换：10000 元素 × 100 轮
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(10000)
	a := make([]int64, n)
	var seed uint64 = 42
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 100000)
	}
	t0 := time.Now()
	for round := int64(0); round < 100; round++ {
		for j := int64(0); j < n-1; j++ {
			if a[j] > a[j+1] {
				a[j], a[j+1] = a[j+1], a[j]
			}
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a[0])
	fmt.Println("T")
	fmt.Println(el)
}
