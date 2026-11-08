// b62_pred_branch —— 可预测分支热循环：500 万次
package main

import (
	"fmt"
	"time"
)

func main() {
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 5000000; i++ {
		if (i*7+3)%5 < 2 {
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
