// b66_integrate —— 离散"积分"累加取模：100 万次（与 C 一致输出整数）
package main

import (
	"fmt"
	"time"
)

func f(x int64) int64 { return (x*x + 3*x + 5) % 1000003 }

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 1000000; i++ {
		acc = (acc + f(i)) % 1000003
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
