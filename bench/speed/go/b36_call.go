// b36_call —— 函数调用热循环：1000 万次三参数求和
package main

import (
	"fmt"
	"time"
)

func add3(a, b, c int64) int64 { return a + b + c }

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 10000000; i++ {
		acc = add3(acc, i, 1)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
