// b87_memcopy_big —— 大块内存拷贝：100MB（1250 万元素）
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(12500000)
	src := make([]int64, n)
	dst := make([]int64, n)
	for i := int64(0); i < n; i++ {
		src[i] = i*7 + 1
	}
	t0 := time.Now()
	copy(dst, src)
	el := time.Since(t0).Nanoseconds()
	chk := dst[0] + dst[6250000] + dst[n-1]
	fmt.Println(chk)
	fmt.Println("T")
	fmt.Println(el)
}
