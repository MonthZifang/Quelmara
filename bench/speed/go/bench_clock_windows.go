//go:build windows

package main

import (
	"syscall"
	"unsafe"
)

var (
	clockKernel    = syscall.NewLazyDLL("kernel32.dll")
	clockCounter   = clockKernel.NewProc("QueryPerformanceCounter")
	clockFrequency = clockKernel.NewProc("QueryPerformanceFrequency")
	clockHz        = performanceFrequency()
)

func performanceFrequency() int64 {
	var hz int64
	if ok, _, _ := clockFrequency.Call(uintptr(unsafe.Pointer(&hz))); ok == 0 || hz <= 0 {
		panic("QueryPerformanceFrequency failed")
	}
	return hz
}

func benchNow() int64 {
	var ticks int64
	if ok, _, _ := clockCounter.Call(uintptr(unsafe.Pointer(&ticks))); ok == 0 {
		panic("QueryPerformanceCounter failed")
	}
	return ticks
}

func benchElapsed(start int64) int64 {
	ticks := benchNow() - start
	// Split seconds and fractional seconds before scaling to avoid overflow.
	return (ticks/clockHz)*1_000_000_000 + (ticks%clockHz)*1_000_000_000/clockHz
}
