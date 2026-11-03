// b16_leibniz —— 浮点：Leibniz 级数 π，2000 万项
package main

import (
	"fmt"
	"time"
)

func main() {
	n := int64(20000000)
	t0 := time.Now()
	s := 0.0
	for i := int64(0); i < n; i++ {
		d := float64(2*i + 1)
		if i%2 == 0 { s += 1.0 / d } else { s -= 1.0 / d }
	}
	pi := s * 4.0
	el := time.Since(t0).Nanoseconds()
	fmt.Printf("%.6f\n", pi)
	fmt.Println("T")
	fmt.Println(el)
}
