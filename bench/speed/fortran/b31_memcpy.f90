! b31_memcpy
program b31_memcpy
  implicit none
  integer(kind=8), parameter :: n = 12500000_8
  integer(kind=8) :: src(n), dst(n)
  integer(kind=8) :: i, t0, t1, rate
  do i = 0_8, n - 1_8
    src(i + 1) = i
  end do
  call system_clock(t0, rate)
  do i = 0_8, n - 1_8
    dst(i + 1) = src(i + 1)
  end do
  call system_clock(t1, rate)
  print '(I0)', dst(n)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b31_memcpy
