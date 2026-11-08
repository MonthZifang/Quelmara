! b1_int —— 整数运算热循环，20M 次
program b1_int
  implicit none
  integer(kind=8) :: n, acc, i, t0, t1, rate
  n = 20000000_8
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, n - 1_8
    acc = acc + mod(i * 7_8, 13_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b1_int
