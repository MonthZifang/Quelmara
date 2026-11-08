// b79_binary_tree —— 有序插入（数组模拟）：50000 元素
package main

import (
	"fmt"
	"time"
)

func main() {
	keys := make([]int64, 50000)
	var n int64 = 0
	var seed uint64 = 42
	t0 := time.Now()
	for i := int64(0); i < 50000; i++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		key := int64(seed % 100000)
		pos := n
		for j := int64(0); j < n; j++ {
			if keys[j] > key {
				pos = j
				break
			}
		}
		for k := n; k > pos; k-- {
			keys[k] = keys[k-1]
		}
		keys[pos] = key
		n++
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(keys[0])
	fmt.Println("T")
	fmt.Println(el)
}
