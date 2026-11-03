// b10_ackermann —— Ackermann(2,8)：深层非原始递归
package main

import (
	"fmt"
	"time"
)

func ack(m, n int64) int64 {
	if m == 0 { return n + 1 }
	if n == 0 { return ack(m-1, 1) }
	return ack(m-1, ack(m, n-1))
}
func main() {
	t0 := time.Now()
	r := ack(2, 8)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
