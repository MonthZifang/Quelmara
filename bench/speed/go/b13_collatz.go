// b13_collatz —— Collatz 序列长度累加(1..30万)
package main

import (
	"fmt"
	"time"
)

func clen(n int64) int64 {
	var c int64
	for n != 1 {
		if n%2 == 0 { n = n / 2 } else { n = 3*n + 1 }
		c++
	}
	return c
}
func main() {
	t0 := time.Now()
	var best, bn int64
	for i := int64(1); i <= 300000; i++ {
		c := clen(i)
		if c > best { best = c; bn = i }
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(best*10000000 + bn)
	fmt.Println("T")
	fmt.Println(el)
}
