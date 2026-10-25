// b6_hash —— 哈希表：30 万插入 + 30 万查找（手写开放寻址，cap=2^20）
package main

import (
	"fmt"
	"time"
)

func main() {
	cap := int64(1048576)
	mask := cap - 1
	n := int64(300000)
	kt := make([]int64, cap)
	vt := make([]int64, cap)
	t0 := time.Now()
	for i := int64(1); i <= n; i++ {
		k := i*3 + 1
		h := (k * 2654435761) & mask
		for kt[h] != 0 {
			h = (h + 1) & mask
		}
		kt[h] = k
		vt[h] = k * 2
	}
	var s int64 = 0
	for i := int64(1); i <= n; i++ {
		k := i*3 + 1
		h := (k * 2654435761) & mask
		for kt[h] != k {
			h = (h + 1) & mask
		}
		s += vt[h]
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(s)
	fmt.Println("T")
	fmt.Println(el)
}
