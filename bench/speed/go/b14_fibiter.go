// b14_fibiter —— 迭代 fib(5000 万)：纯循环 vs 递归对照
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(50000000)
	t0 := time.Now()
	var a, b int64 = 0, 1
	for i := int64(0); i < n; i++ {
		t := a + b
		a = b
		b = t % 1000000007
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a)
	fmt.Println("T")
	fmt.Println(el)
}
