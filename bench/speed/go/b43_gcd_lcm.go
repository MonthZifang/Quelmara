// b43_gcd_lcm —— 100 万次 gcd(i, 1000001-i)
package main

import (
	"fmt"
	"time"
)

func gcd(a, b int64) int64 {
	for b != 0 {
		t := b
		b = a % b
		a = t
	}
	return a
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(1); i <= 1000000; i++ {
		acc += gcd(i, 1000000-i+1)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
