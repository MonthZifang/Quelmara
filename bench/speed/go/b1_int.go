// b1_int —— 整数运算热循环：2000 万次 (i*7)%13
// 末行打印 "T" + 负载耗时（纳秒），进程创建成本不计入。
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(20000000)
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < n; i++ {
		acc += (i * 7) % 13
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
