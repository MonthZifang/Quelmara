! b26_maxsub —— 经典一维 DP：Kadane 最大子数组 2000 万
program b26_maxsub
  implicit none
  integer(kind=8), parameter :: n = 20000000_8
  integer(kind=8) :: seed, i, v, best, cur, t0, t1, rate
  seed = 42_8
  call system_clock(t0, rate)
  best = 0_8; cur = 0_8
  do i = 0_8, n - 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    v = mod(seed, 201_8) - 100_8
    cur = cur + v
    if (cur < 0_8) cur = 0_8
    if (cur > best) best = cur
  end do
  call system_clock(t1, rate)
  print '(I0)', best
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b26_maxsub
