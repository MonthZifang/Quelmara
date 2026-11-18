//go:build !windows

package main

import "time"

// time.Time retains Go's monotonic clock reading for elapsed-time calculations.
func benchNow() time.Time                { return time.Now() }
func benchElapsed(start time.Time) int64 { return time.Since(start).Nanoseconds() }
