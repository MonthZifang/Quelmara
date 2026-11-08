// b77_rec_fib —— 双重递归斐波那契：fib(25)
package main

import (
	"fmt"
	"time"
)

func fib(n int64) int64 {
	if n <= 1 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	t0 := time.Now()
	r := fib(25)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
