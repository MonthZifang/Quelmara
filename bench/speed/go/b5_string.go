// b5_string —— 字符串：50 万次 int→str→int
package main

import (
	"fmt"
	"strconv"
)

func main() {
	n := int64(500000)
	var acc int64 = 0
	t0 := benchNow()
	for i := int64(0); i < n; i++ {
		s := strconv.FormatInt(i, 10)
		acc += int64(len(s))
		v, _ := strconv.ParseInt(s, 10, 64)
		acc += v
	}
	el := benchElapsed(t0)
	fmt.Println(acc)
	fmt.Println("T")
	fmt.Println(el)
}
