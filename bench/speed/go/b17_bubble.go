// b17_bubble —— 冒泡排序 8 万元素（最坏分支 + 交换开销）
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(80000)
	a := make([]int64, n)
	seed := uint64(12345)
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 100000)
	}
	t0 := time.Now()
	for x := int64(0); x < n; x++ {
		for y := int64(0); y < n-1-x; y++ {
			if a[y] > a[y+1] { a[y], a[y+1] = a[y+1], a[y] }
		}
	}
	el := time.Since(t0).Nanoseconds()
	var chk int64
	for i := int64(0); i < n; i++ { chk = (chk + a[i]*(i+1)) % 1000000007 }
	fmt.Println(chk)
	fmt.Println("T")
	fmt.Println(el)
}
