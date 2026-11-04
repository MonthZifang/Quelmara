# b12_gcd —— 整数：3000 万次辗转相除
import std/times

proc gcd(a, b: int64): int64 =
  var x = a
  var y = b
  while y != 0:
    let t = y
    y = x mod y
    x = t
  return x

when isMainModule:
  let n: int64 = 30000000
  let t0 = cpuTime()
  var s: int64 = 0
  for i in 1..n:
    s += gcd(i, 1000000 - i)
  let t1 = cpuTime()
  echo s
  echo "T"
  echo int64((t1 - t0) * 1e9)
