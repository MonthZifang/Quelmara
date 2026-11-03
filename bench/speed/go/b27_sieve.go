// b27_sieve —— 埃氏筛 5000 万
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(10000000)
	t0 := time.Now()
	c := make([]uint8, n+1)
	for i := int64(0); i <= n; i++ { c[i] = 1 }
	c[0] = 0; c[1] = 0
	for p := int64(2); p*p <= n; p++ {
		if c[p] == 1 {
			for q := p * p; q <= n; q += p { c[q] = 0 }
		}
	}
	var cnt int64
	for i := int64(0); i <= n; i++ { cnt += int64(c[i]) }
	el := time.Since(t0).Nanoseconds()
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
