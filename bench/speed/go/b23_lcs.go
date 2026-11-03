// b23_lcs —— DP：最长公共子序列 1500×1500
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1500)
	prev := make([]int64, n+1)
	cur := make([]int64, n+1)
	t0 := time.Now()
	for r := int64(1); r <= n; r++ {
		for c := int64(1); c <= n; c++ {
			av := (r*7 + 3) % 4
			bv := (c*11 + 5) % 4
			if av == bv {
				cur[c] = prev[c-1] + 1
			} else if prev[c] > cur[c-1] {
				cur[c] = prev[c]
			} else {
				cur[c] = cur[c-1]
			}
		}
		for c := int64(0); c <= n; c++ { prev[c] = cur[c] }
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(prev[n])
	fmt.Println("T")
	fmt.Println(el)
}
