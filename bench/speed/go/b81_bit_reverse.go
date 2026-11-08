// b81_bit_reverse —— 100 万次位反转后异或累加
package main

import (
	"fmt"
	"time"
)

func bitrev(x int64) int64 {
	v := x
	var r int64 = 0
	for i := 0; i < 32; i++ {
		r = (r << 1) | (v & 1)
		v >>= 1
	}
	return r
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for j := int64(0); j < 1000000; j++ {
		acc ^= bitrev(j)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
