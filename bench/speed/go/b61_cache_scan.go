// b61_cache_scan —— 顺序缓存扫描：100 万元素 ×10 遍
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000000)
	a := make([]int64, n)
	for i := int64(0); i < n; i++ {
		a[i] = i
	}
	t0 := time.Now()
	var acc int64 = 0
	for j := int64(0); j < 10; j++ {
		for k := int64(0); k < n; k++ {
			acc += a[k]
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
