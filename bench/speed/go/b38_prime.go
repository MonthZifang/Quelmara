// b38_prime —— 素数计数：0..99999
package main

import (
	"fmt"
	"time"
)

func isPrime(n int64) int64 {
	if n < 2 {
		return 0
	}
	if n == 2 {
		return 1
	}
	if n%2 == 0 {
		return 0
	}
	for d := int64(3); d*d <= n; d += 2 {
		if n%d == 0 {
			return 0
		}
	}
	return 1
}

func main() {
	var cnt int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 100000; i++ {
		if isPrime(i) == 1 {
			cnt++
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
