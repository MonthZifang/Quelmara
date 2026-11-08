// b44_stack_sim —— 栈模拟：100 万次 push + 条件自增
package main

import (
	"fmt"
	"time"
)

func main() {
	st := make([]int64, 1000000)
	var top int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 1000000; i++ {
		st[top] = i
		top++
		if i%3 == 0 && top > 0 {
			st[top-1]++
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(st[top-1])
	fmt.Println("T")
	fmt.Println(el)
}
