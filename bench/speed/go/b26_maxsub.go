// b26_maxsub —— 经典一维 DP：Kadane 最大子数组 2000 万
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(20000000)
	seed := uint64(42)
	t0 := time.Now()
	var best, cur int64
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		v := int64(seed%201) - 100
		cur += v
		if cur < 0 { cur = 0 }
		if cur > best { best = cur }
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(best)
	fmt.Println("T")
	fmt.Println(el)
}
