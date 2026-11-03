// b18_insertion —— 排序：插入排序 8 万元素
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
	for x := int64(1); x < n; x++ {
		key := a[x]
		y := x - 1
		for y >= 0 && a[y] > key { a[y+1] = a[y]; y-- }
		a[y+1] = key
	}
	el := time.Since(t0).Nanoseconds()
	var chk int64
	for i := int64(0); i < n; i++ { chk = (chk + a[i]*(i+1)) % 1000000007 }
	fmt.Println(chk)
	fmt.Println("T")
	fmt.Println(el)
}
