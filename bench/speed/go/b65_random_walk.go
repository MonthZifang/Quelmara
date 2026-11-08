// b65_random_walk —— 确定性随机游走：200 万步
package main

import (
	"fmt"
	"time"
)

func main() {
	var x, y int64 = 0, 0
	var seed uint64 = 12345
	t0 := time.Now()
	for i := int64(0); i < 2000000; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		d := int64(seed % 4)
		if d == 0 {
			x++
		} else if d == 1 {
			x--
		} else if d == 2 {
			y++
		} else {
			y--
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(x*1000000 + y)
	fmt.Println("T")
	fmt.Println(el)
}
