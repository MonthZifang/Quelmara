! b22_knapsack —— 0/1 背包 DP（800 件 × 800 容量）
program b22_knapsack
  implicit none
  integer(kind=8), parameter :: n = 800_8, cap = 800_8
  integer(kind=8) :: wt(n), vl(n), dp(0:cap)
  integer(kind=8) :: seed, i, it, c, cand, t0, t1, rate
  seed = 999_8
  do i = 0_8, n - 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    wt(i + 1) = mod(seed, 50_8) + 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    vl(i + 1) = mod(seed, 100_8) + 1_8
  end do
  call system_clock(t0, rate)
  dp = 0_8
  do it = 0_8, n - 1_8
    c = cap
    do while (c >= wt(it + 1))
      cand = dp(c - wt(it + 1)) + vl(it + 1)
      if (cand > dp(c)) dp(c) = cand
      c = c - 1_8
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', dp(cap)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b22_knapsack
