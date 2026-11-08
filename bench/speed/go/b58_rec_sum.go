// b58_rec_sum —— 递归求和：100 次 rec_sum(10000)
package main

import (
	"fmt"
	"time"
)

func recSum(n int64) int64 {
	if n <= 0 {
		return 0
	}
	return n + recSum(n-1)
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(1); i <= 100; i++ {
		acc += recSum(10000)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
