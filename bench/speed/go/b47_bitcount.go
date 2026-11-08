// b47_bitcount —— 1000 万次 popcount
package main

import (
	"fmt"
	"time"
)

func popcount(x int64) int64 {
	var c int64 = 0
	for x != 0 {
		c += x & 1
		x >>= 1
	}
	return c
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 10000000; i++ {
		acc += popcount(i)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
