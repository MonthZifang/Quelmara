! b14_fibiter —— 迭代 fib(5000 万)
program b14_fibiter
  implicit none
  integer(kind=8), parameter :: n = 50000000_8
  integer(kind=8) :: a, b, t, i, t0, t1, rate
  call system_clock(t0, rate)
  a = 0_8; b = 1_8
  do i = 0_8, n - 1_8
    t = a + b
    a = b
    b = mod(t, 1000000007_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', a
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b14_fibiter
