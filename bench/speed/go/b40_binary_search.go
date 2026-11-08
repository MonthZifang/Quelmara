// b40_binary_search —— 二分查找：100 万有序数组 × 100 万次查询
package main

import (
	"fmt"
	"time"
)

func bsearchImpl(a []int64, n, target int64) int64 {
	lo, hi := int64(0), n-1
	for lo <= hi {
		mid := (lo + hi) / 2
		if a[mid] == target {
			return mid
		}
		if a[mid] < target {
			lo = mid + 1
		} else {
			hi = mid - 1
		}
	}
	return -1
}

func main() {
	n := int64(1000000)
	a := make([]int64, n)
	for i := int64(0); i < n; i++ {
		a[i] = i * 2
	}
	t0 := time.Now()
	var found int64 = 0
	for j := int64(0); j < 1000000; j++ {
		if bsearchImpl(a, n, j*2) >= 0 {
			found++
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(found)
	fmt.Println("T")
	fmt.Println(el)
}
