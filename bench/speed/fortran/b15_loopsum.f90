! b15_loopsum —— 最朴素循环累加 2 亿次（循环开销基线）
program b15_loopsum
  implicit none
  integer(kind=8), parameter :: n = 200000000_8
  integer(kind=8) :: s, x, i, t0, t1, rate
  call system_clock(t0, rate)
  s = 0_8
  x = 1_8
  do i = 0_8, n - 1_8
    x = ior(x * 31_8 + i, 1_8)
    s = s + iand(x, 1023_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', s
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b15_loopsum
