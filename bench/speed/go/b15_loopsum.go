// b15_loopsum —— 最朴素循环累加 2 亿次（循环开销基线）
//
// 用依赖链防止编译器折叠成闭式解（见 C 版的说明）。
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(200000000)
	t0 := time.Now()
	var s int64
	x := int64(1)
	for i := int64(0); i < n; i++ {
		x = (x*31 + i) | 1
		s += x & 1023
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(s)
	fmt.Println("T")
	fmt.Println(el)
}
