// b76_io_line —— 逐行求和：100 万元素取模累加
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000000)
	lines := make([]int64, n)
	for i := int64(0); i < n; i++ {
		lines[i] = i*7 + 3
	}
	t0 := time.Now()
	var sum int64 = 0
	for j := int64(0); j < n; j++ {
		sum += lines[j] % 100
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(sum)
	fmt.Println("T")
	fmt.Println(el)
}
