// b69_hash_fib —— Fibonacci 风格哈希计数：50 万键
package main

import (
	"fmt"
	"time"
)

func fibHash(key, cap int64) int64 {
	return ((key*2654435761)%cap + cap) % cap
}

func main() {
	cap := int64(524288)
	tab := make([]int64, cap)
	t0 := time.Now()
	var cnt int64 = 0
	for j := int64(0); j < 500000; j++ {
		h := fibHash(j, cap)
		tab[h]++
		cnt++
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
