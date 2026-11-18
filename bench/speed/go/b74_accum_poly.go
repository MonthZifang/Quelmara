// b74_accum_poly —— 多项式累加取模：500 万次
package main

import (
	"fmt"
)

func main() {
	var acc int64 = 0
	t0 := benchNow()
	for n := int64(1); n <= 5000000; n++ {
		var s int64 = 0
		for k := 0; k < 5; k++ {
			s = s*n + int64(k*3) + 1
		}
		acc += s % 1000003
	}
	el := benchElapsed(t0)
	fmt.Println(acc % 1000003)
	fmt.Println("T")
	fmt.Println(el)
}
