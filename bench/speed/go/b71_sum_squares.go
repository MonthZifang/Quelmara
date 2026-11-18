// b71_sum_squares —— 100 万平方累加取模
package main

import (
	"fmt"
)

func main() {
	var acc int64 = 0
	t0 := benchNow()
	for i := int64(1); i <= 1000000; i++ {
		acc += i * i
	}
	el := benchElapsed(t0)
	fmt.Println(acc % 1000003)
	fmt.Println("T")
	fmt.Println(el)
}
