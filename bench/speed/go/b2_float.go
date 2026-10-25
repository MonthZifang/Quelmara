// b2_float —— 浮点运算：调和级数前 500 万项
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(5000000)
	var acc float64 = 0
	t0 := time.Now()
	for i := int64(1); i <= n; i++ {
		acc += 1.0 / float64(i)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Printf("%.6f\n", acc)
	fmt.Println("T")
	fmt.Println(el)
}
