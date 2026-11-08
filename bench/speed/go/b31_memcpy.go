// b31_memcpy —— 大块内存拷贝：1250 万元素 int64 数组
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(12500000)
	src := make([]int64, n)
	for i := int64(0); i < n; i++ {
		src[i] = i
	}
	dst := make([]int64, n)
	t0 := time.Now()
	for j := int64(0); j < n; j++ {
		dst[j] = src[j]
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(dst[n-1])
	fmt.Println("T")
	fmt.Println(el)
}
