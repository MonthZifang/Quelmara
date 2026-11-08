// b33_startup —— 进程启动/函数调用开销：4 次 init()
package main

import (
	"fmt"
	"time"
)

func initf() int64 {
	var s int64 = 0
	for i := int64(0); i < 1000; i++ {
		s += i
	}
	return s
}

func main() {
	t0 := time.Now()
	a, b, c, d := initf(), initf(), initf(), initf()
	el := time.Since(t0).Nanoseconds()
	fmt.Println(a + b + c + d)
	fmt.Println("T")
	fmt.Println(el)
}
