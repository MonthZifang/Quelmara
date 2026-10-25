// b8_threads4 —— 同样 4000 万次总量，拆成 4 个 goroutine
package main

import (
	"fmt"
	"sync"
	"time"
)

func work(n int64) int64 {
	var acc int64 = 0
	for i := int64(0); i < n; i++ {
		acc += (i * 7) % 13
	}
	return acc
}

func main() {
	var res [4]int64
	var wg sync.WaitGroup
	t0 := time.Now()
	for k := 0; k < 4; k++ {
		wg.Add(1)
		go func(k int) {
			defer wg.Done()
			res[k] = work(40000000)
		}(k)
	}
	wg.Wait()
	el := time.Since(t0).Nanoseconds()
	fmt.Println(res[0] + res[1] + res[2] + res[3])
	fmt.Println("T")
	fmt.Println(el)
}
