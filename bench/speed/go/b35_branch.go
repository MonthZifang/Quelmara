// b35_branch —— 分支预测热循环：2000 万次条件加减
package main

import (
	"fmt"
	"time"
)

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 20000000; i++ {
		if (i & 3) == 0 {
			acc += 1
		} else {
			acc -= 1
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
