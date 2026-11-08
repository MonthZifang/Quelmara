// b56_sieve_opt —— 优化素数筛：0..2000000
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(2000000)
	flags := make([]int64, n+1)
	for i := int64(0); i <= n; i++ {
		flags[i] = 1
	}
	flags[0] = 0
	flags[1] = 0
	t0 := time.Now()
	for p := int64(2); p*p <= n; p++ {
		if flags[p] != 0 {
			for q := p * p; q <= n; q += p {
				flags[q] = 0
			}
		}
	}
	var cnt int64 = 0
	for k := int64(2); k <= n; k++ {
		if flags[k] != 0 {
			cnt++
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
