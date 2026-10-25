// b4_array —— 数组：200 万元素写入 + 顺序 + 跨步遍历
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(2000000)
	v := make([]int64, n)
	t0 := time.Now()
	for i := int64(0); i < n; i++ {
		v[i] = i*3 + 1
	}
	var s int64 = 0
	for i := int64(0); i < n; i++ {
		s += v[i]
	}
	var t int64 = 0
	for i := int64(0); i < n; i += 7 {
		t += v[i]
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(s)
	fmt.Println(t)
	fmt.Println("T")
	fmt.Println(el)
}
