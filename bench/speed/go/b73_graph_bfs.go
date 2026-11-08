// b73_graph_bfs —— 邻接矩阵 BFS：1000 节点，5000 边
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(1000)
	adj := make([]int64, n*n)
	var seed uint64 = 55
	for e := int64(0); e < 5000; e++ {
		seed = (seed*1103515245 + 12345) % 2147483648
		u := int64(seed % uint64(n))
		seed = (seed*1103515245 + 12345) % 2147483648
		v := int64(seed % uint64(n))
		adj[u*n+v] = 1
	}
	t0 := time.Now()
	visited := make([]int64, n)
	queue := make([]int64, n)
	front, back := int64(0), int64(0)
	queue[back] = 0
	back++
	visited[0] = 1
	var cnt int64 = 0
	for front < back {
		u := queue[front]
		front++
		cnt++
		for v := int64(0); v < n; v++ {
			if adj[u*n+v] != 0 && visited[v] == 0 {
				visited[v] = 1
				queue[back] = v
				back++
			}
		}
	}
	el := time.Since(t0).Nanoseconds()
	fmt.Println(cnt)
	fmt.Println("T")
	fmt.Println(el)
}
