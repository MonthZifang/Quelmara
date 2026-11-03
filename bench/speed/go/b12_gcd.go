// b12_gcd —— GCD 密集：3000 万次辗转相除
package main

import (
	"fmt"
	"time"
)

func gcd(a, b int64) int64 {
	for b != 0 { a, b = b, a%b }
	return a
}
func main() {
	n := int64(30000000)
	t0 := time.Now()
	var s int64
	for i := int64(1); i <= n; i++ { s += gcd(i, 1000000-i) }
	el := time.Since(t0).Nanoseconds()
	fmt.Println(s)
	fmt.Println("T")
	fmt.Println(el)
}
