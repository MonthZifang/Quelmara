// b55_hash_chain —— 链式哈希计数：20 万键入 262144 桶
package main

import (
	"fmt"
)

func main() {
	cap := int64(262144)
	buckets := make([]int64, cap)
	t0 := benchNow()
	var cnt int64 = 0
	for j := int64(0); j < 200000; j++ {
		h := (j * 2654435761) % cap
		buckets[h]++
		cnt++
	}
	el := benchElapsed(t0)
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
