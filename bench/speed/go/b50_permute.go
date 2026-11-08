// b50_permute —— 全排列哈希累加：10 元素
package main

import (
	"fmt"
	"time"
)

func perm(arr []int64, k, n int, acc int64) int64 {
	if k == n {
		var h int64 = 0
		for i := 0; i < n; i++ {
			h = h*31 + arr[i]
		}
		return acc + (h % 1000003)
	}
	s := acc
	for i := k; i < n; i++ {
		arr[k], arr[i] = arr[i], arr[k]
		s = perm(arr, k+1, n, s)
		arr[k], arr[i] = arr[i], arr[k]
	}
	return s
}

func main() {
	a := make([]int64, 10)
	for i := 0; i < 10; i++ {
		a[i] = int64(i + 1)
	}
	t0 := time.Now()
	r := perm(a, 0, 10, 0)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
