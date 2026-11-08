// b39_hash_open —— 开放寻址哈希插入+查找：50 万键
package main

import (
	"fmt"
	"time"
)

func main() {
	cap := int64(1048576)
	keys := make([]int64, cap)
	vals := make([]int64, cap)
	t0 := time.Now()
	for j := int64(0); j < 500000; j++ {
		h := (j * 2654435761) % cap
		keys[h] = j
		vals[h] = j * 2
	}
	var found int64 = 0
	for k := int64(0); k < 500000; k++ {
		h := (k * 2654435761) % cap
		if keys[h] == k {
			found++
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(found)
	fmt.Println("T")
	fmt.Println(el)
}
