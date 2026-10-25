// b7_sort —— 排序：20 万伪随机 int 快排（手写）
package main

import (
	"fmt"
	"time"
)

func qsort(a []int64, lo, hi int64) {
	if lo >= hi {
		return
	}
	p := a[hi]
	i := lo
	for j := lo; j < hi; j++ {
		if a[j] < p {
			a[i], a[j] = a[j], a[i]
			i++
		}
	}
	a[i], a[hi] = a[hi], a[i]
	qsort(a, lo, i-1)
	qsort(a, i+1, hi)
}

func main() {
	n := int64(200000)
	v := make([]int64, n)
	x := int64(12345)
	for i := int64(0); i < n; i++ {
		x = (x*1103515245 + 12345) & 2147483647
		v[i] = x
	}
	t0 := time.Now()
	qsort(v, 0, n-1)
	el := time.Since(t0).Nanoseconds()
	var s int64 = 0
	for i := int64(0); i < n; i++ {
		s += v[i] % 1000
	}
	fmt.Println(v[0])
	fmt.Println(v[n-1])
	fmt.Println(s)
	fmt.Println("T")
	fmt.Println(el)
}
