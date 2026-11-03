// b15_loopsum —— 最朴素循环累加 2 亿次
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(200000000)
	t0 := time.Now()
	var s int64
	for i := int64(0); i < n; i++ { s += i }
	el := time.Since(t0).Nanoseconds()
	fmt.Println(s)
	fmt.Println("T")
	fmt.Println(el)
}
