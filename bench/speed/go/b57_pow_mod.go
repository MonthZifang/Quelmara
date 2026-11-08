// b57_pow_mod —— 100 万次 pow_mod(i,i,1000003) 累加取模
package main

import (
	"fmt"
	"time"
)

func powMod(base, exp, mod int64) int64 {
	var result int64 = 1
	b := base % mod
	for exp > 0 {
		if exp%2 == 1 {
			result = (result * b) % mod
		}
		b = (b * b) % mod
		exp /= 2
	}
	return result
}

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(1); i <= 1000000; i++ {
		acc = (acc + powMod(i, i, 1000003)) % 1000003
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
