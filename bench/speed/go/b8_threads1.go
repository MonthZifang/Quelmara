// b8_threads1 —— 并发基线：单线程 4000 万次整数运算
package main

import (
	"fmt"
	"time"
)

func work(n int64) int64 {
	var acc int64 = 0
	for i := int64(0); i < n; i++ {
		acc += (i * 7) % 13
	}
	return acc
}

func main() {
	t0 := time.Now()
	r := work(160000000)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
