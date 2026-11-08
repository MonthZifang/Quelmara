// b70_lin_search —— 线性查找：1000 元素 × 100 万次随机目标
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000)
	a := make([]int64, n)
	for i := int64(0); i < n; i++ {
		a[i] = i*3 + 7
	}
	t0 := time.Now()
	var found int64 = 0
	for j := int64(0); j < 1000000; j++ {
		target := (j*37 + 11) % 3000
		for k := int64(0); k < n; k++ {
			if a[k] == target {
				found++
			}
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(found)
	fmt.Println("T")
	fmt.Println(el)
}
