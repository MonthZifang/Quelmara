// b34_bitops —— 位运算热循环：2000 万次异或/移位/与/或
package main

import (
	"fmt"
	"time"
)

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 20000000; i++ {
		acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5))
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
