// b32_io_write —— 缓冲填充：100 万元素 int64 数组
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000000)
	buf := make([]int64, n)
	t0 := time.Now()
	for i := int64(0); i < n; i++ {
		buf[i] = i*2 + 1
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(buf[n-1])
	fmt.Println("T")
	fmt.Println(el)
}
