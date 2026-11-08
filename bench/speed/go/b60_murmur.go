// b60_murmur —— MurmurHash 风格混合：100 万次
package main

import (
	"fmt"
	"time"
)

func murmur(h, k int64) int64 {
	key := k
	key *= -862048943
	key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFF)
	key *= -862048943
	h ^= key
	h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFF)
	return h*5 + 1
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 1000000; i++ {
		acc = murmur(acc, i)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
