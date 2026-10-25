// b3_recursion —— 递归：朴素 fib(30)
package main

import (
	"fmt"
	"time"
)

func fib(n int64) int64 {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	t0 := time.Now()
	r := fib(30)
	el := time.Since(t0).Nanoseconds()
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
