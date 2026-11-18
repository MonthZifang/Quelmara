// b45_accumulate —— 累积多项式求值 + 取模：100 万次
package main

import (
	"fmt"
)

func main() {
	var acc int64 = 0
	t0 := benchNow()
	for n := int64(1); n <= 1000000; n++ {
		var s int64 = 0
		for k := 0; k < 10; k++ {
			s = s*n + int64(k)
		}
		acc += s % 1000003
	}
	el := benchElapsed(t0)
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
