# b10_ackermann —— 递归：Ackermann(2,8)
import std/times

proc ack(m, n: int64): int64 =
  if m == 0: return n + 1
  if n == 0: return ack(m - 1, 1)
  return ack(m - 1, ack(m, n - 1))

when isMainModule:
  let t0 = cpuTime()
  let r = ack(2, 8)
  let t1 = cpuTime()
  echo r
  echo "T"
  echo int64((t1 - t0) * 1e9)
