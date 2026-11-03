// b22_knapsack —— 0/1 背包 DP（800 件 × 800 容量）
package main

import (
	"fmt"
	"time"
)

func main() {
	n, cap := int64(800), int64(800)
	wt := make([]int64, n)
	vl := make([]int64, n)
	seed := uint64(999)
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		wt[i] = int64(seed%50 + 1)
		seed = (seed*1103515245 + 12345) % 2147483648
		vl[i] = int64(seed%100 + 1)
	}
	t0 := time.Now()
	dp := make([]int64, cap+1)
	for it := int64(0); it < n; it++ {
		for c := cap; c >= wt[it]; c-- {
			cand := dp[c-wt[it]] + vl[it]
			if cand > dp[c] { dp[c] = cand }
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(dp[cap])
	fmt.Println("T")
	fmt.Println(el)
}
