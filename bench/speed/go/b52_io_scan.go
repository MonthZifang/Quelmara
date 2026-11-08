// b52_io_scan —— 缓冲扫描求和：100 万元素
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000000)
	buf := make([]int64, n)
	for i := int64(0); i < n; i++ {
		buf[i] = i*3 + 1
	}
	t0 := time.Now()
	var sum int64 = 0
	for j := int64(0); j < n; j++ {
		sum += buf[j]
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(sum)
	fmt.Println("T")
	fmt.Println(el)
}
