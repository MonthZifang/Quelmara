// b84_pair_swap —— 键值对互换：100 万对
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000000)
	keys := make([]int64, n)
	vals := make([]int64, n)
	for i := int64(0); i < n; i++ {
		keys[i] = i
		vals[i] = i * 2
	}
	t0 := time.Now()
	for j := int64(0); j < n; j++ {
		k := keys[j]
		v := vals[j]
		keys[j] = v
		vals[j] = k
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(keys[0] + vals[0])
	fmt.Println("T")
	fmt.Println(el)
}
