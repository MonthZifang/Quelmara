// b11_nqueens —— N 皇后(8)：回溯 + 数组标记
package main

import (
	"fmt"
	"time"
)

func solve(col []int64, n, r int64) int64 {
	if r == n { return 1 }
	var cnt int64
	for c := int64(0); c < n; c++ {
		ok := true
		for k := int64(0); k < r; k++ {
			cc := col[k]
			if cc == c { ok = false }
			d := cc - c
			if d == k-r || d == r-k { ok = false }
		}
		if ok { col[r] = c; cnt += solve(col, n, r+1) }
	}
	return cnt
}
func main() {
	n := int64(8)
	col := make([]int64, n)
	t0 := time.Now()
	var total int64
	for rep := 0; rep < 2000; rep++ { total += solve(col, n, 0) }
	el := time.Since(t0).Nanoseconds()
	fmt.Println(total)
	fmt.Println("T")
	fmt.Println(el)
}
