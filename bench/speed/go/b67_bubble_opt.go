// b67_bubble_opt —— 带交换标志的冒泡排序：5000 元素
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(5000)
	a := make([]int64, n)
	var seed uint64 = 99
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 100000)
	}
	t0 := time.Now()
	swapped := 1
	for swapped != 0 {
		swapped = 0
		for j := int64(0); j < n-1; j++ {
			if a[j] > a[j+1] {
				a[j], a[j+1] = a[j+1], a[j]
				swapped = 1
			}
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a[0])
	fmt.Println("T")
	fmt.Println(el)
}
