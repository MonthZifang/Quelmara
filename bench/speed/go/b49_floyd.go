// b49_floyd —— Floyd-Warshall：100 节点，初始化 300 条边
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(100)
	sz := n * n
	dist := make([]int64, sz)
	for i := int64(0); i < sz; i++ {
		dist[i] = 999999
	}
	for k := int64(0); k < n; k++ {
		dist[k*n+k] = 0
	}
	var seed uint64 = 7
	for e := int64(0); e < 300; e++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		u := int64(seed % uint64(n))
		seed = (seed*1103515245 + 12345) % 2147483648
		v := int64(seed % uint64(n))
		seed = (seed*1103515245 + 12345) % 2147483648
		w := int64(seed%100 + 1)
		dist[u*n+v] = w
	}
	t0 := time.Now()
	for a := int64(0); a < n; a++ {
		for b := int64(0); b < n; b++ {
			for c := int64(0); c < n; c++ {
				d1 := dist[b*n+c]
				d2 := dist[b*n+a] + dist[a*n+c]
				if d2 < d1 {
					dist[b*n+c] = d2
				}
			}
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(dist[1])
	fmt.Println("T")
	fmt.Println(el)
}
