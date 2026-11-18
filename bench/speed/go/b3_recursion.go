// b3_recursion —— 递归：朴素 fib(30)
package main

import (
	"fmt"
)

func fib(n int64) int64 {
	if n < 2 {
		return n
	}
	return fib(n-1) + fib(n-2)
}

func main() {
	t0 := benchNow()
	r := fib(30)
	el := benchElapsed(t0)
	fmt.Println(r)
	fmt.Println("T")
	fmt.Println(el)
}
