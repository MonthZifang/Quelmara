# b28_matrix —— 数值：矩阵乘法 300x300
import std/times

when isMainModule:
  let n = 300
  let sz = n * n
  var a = newSeq[int64](sz)
  var b = newSeq[int64](sz)
  var c = newSeq[int64](sz)
  var seed: uint64 = 7
  for i in 0..<sz:
    seed = (seed * 1103515245 + 12345) mod 2147483648'u64
    a[i] = int64(seed mod 100)
    seed = (seed * 1103515245 + 12345) mod 2147483648'u64
    b[i] = int64(seed mod 100)
  let t0 = cpuTime()
  for r in 0..<n:
    for k in 0..<n:
      let av = a[r * n + k]
      for j in 0..<n:
        c[r * n + j] += av * b[k * n + j]
  let t1 = cpuTime()
  var chk: int64 = 0
  for i in 0..<sz:
    chk = (chk + c[i]) mod 1000000007
  echo chk
  echo "T"
  echo int64((t1 - t0) * 1e9)
