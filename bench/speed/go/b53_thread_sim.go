// b53_thread_sim —— 4 段并行求和（确定性结果），Go 用 goroutine 复现
package main

import (
	"fmt"
	"sync"
	"time"
)

func work(start, end int64) int64 {
	var s int64 = 0
	for i := start; i < end; i++ {
		s += i*2 + 1
	}
	return s
}

func main() {
	n := int64(10000000)
	var res [4]int64
	var wg sync.WaitGroup
	t0 := time.Now()
	ranges := [4][2]int64{{0, n / 4}, {n / 4, n / 2}, {n / 2, 3 * n / 4}, {3 * n / 4, n}}
	for k := 0; k < 4; k++ {
		wg.Add(1)
		go func(k int) {
			defer wg.Done()
			res[k] = work(ranges[k][0], ranges[k][1])
		}(k)
	}
	wg.Wait()
	el := time.Since(t0).Nanoseconds()
	fmt.Println(res[0] + res[1] + res[2] + res[3])
	fmt.Println("T")
	fmt.Println(el)
}
