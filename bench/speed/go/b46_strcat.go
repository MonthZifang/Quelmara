// b46_strcat —— 字符串拼接长度累加：10 万次 "hello world 12345"
package main

import (
	"fmt"
	"time"
)

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 100000; i++ {
		s := fmt.Sprintf("%s %s %s", "hello", "world", "12345")
		acc += int64(len(s))
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
