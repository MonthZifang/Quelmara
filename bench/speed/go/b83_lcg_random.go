// b83_lcg_random —— LCG 随机累加：1000 万次
package main

import (
	"fmt"
	"time"
)

func main() {
	var seed uint64 = 12345
	var acc int64 = 0
	t0 := time.Now()
	for i := int64(0); i < 10000000; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		acc += int64(seed % 100)
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
