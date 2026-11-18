// b78_sum_digits —— 100 万次数字各位求和
package main

import (
	"fmt"
)

func digitSum(n int64) int64 {
	var s int64 = 0
	for n > 0 {
		s += n % 10
		n /= 10
	}
	return s
}

func main() {
	var acc int64 = 0
	t0 := benchNow()
	for i := int64(0); i < 1000000; i++ {
		acc += digitSum(i)
	}
	el := benchElapsed(t0)
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
