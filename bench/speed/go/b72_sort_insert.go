// b72_sort_insert —— 插入排序：10000 元素
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(10000)
	a := make([]int64, n)
	var seed uint64 = 777
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 100000)
	}
	t0 := time.Now()
	for x := int64(1); x < n; x++ {
		key := a[x]
		y := x - 1
		for y >= 0 && a[y] > key {
			a[y+1] = a[y]
			y--
		}
		a[y+1] = key
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a[0])
	fmt.Println("T")
	fmt.Println(el)
}
