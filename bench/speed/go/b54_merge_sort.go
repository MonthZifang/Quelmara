// b54_merge_sort —— 10 万元素归并排序，输出最小值
package main

import (
	"fmt"
	"time"
)

func merge(a, tmp []int64, lo, mid, hi int64) {
	i, j, k := lo, mid, int64(0)
	for i < mid && j < hi {
		if a[i] <= a[j] {
			tmp[k] = a[i]
			i++
		} else {
			tmp[k] = a[j]
			j++
		}
		k++
	}
	for i < mid {
		tmp[k] = a[i]
		i++
		k++
	}
	for j < hi {
		tmp[k] = a[j]
		j++
		k++
	}
	for x := int64(0); x < k; x++ {
		a[lo+x] = tmp[x]
	}
}

func msort(a, tmp []int64, lo, hi int64) {
	if hi-lo <= 1 {
		return
	}
	mid := (lo + hi) / 2
	msort(a, tmp, lo, mid)
	msort(a, tmp, mid, hi)
	merge(a, tmp, lo, mid, hi)
}

func main() {
	n := int64(100000)
	a := make([]int64, n)
	tmp := make([]int64, n)
	var seed uint64 = 12345
	for i := int64(0); i < n; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		a[i] = int64(seed % 1000000)
	}
	t0 := time.Now()
	msort(a, tmp, 0, n)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a[0])
	fmt.Println("T")
	fmt.Println(el)
}
