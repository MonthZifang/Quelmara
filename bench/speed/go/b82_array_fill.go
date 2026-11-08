// b82_array_fill —— 500 万元素数组填充
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(5000000)
	a := make([]int64, n)
	t0 := time.Now()
	for i := int64(0); i < n; i++ {
		a[i] = i*2 + 1
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a[n-1])
	fmt.Println("T")
	fmt.Println(el)
}
