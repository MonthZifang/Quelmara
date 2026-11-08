! b87_memcopy_big
program b87_memcopy_big
  implicit none
  integer(kind=8), parameter :: n = 12500000_8
  integer(kind=8) :: src(n), dst(n)
  integer(kind=8) :: i, t0, t1, rate, chk
  do i = 0_8, n - 1_8
    src(i + 1) = i * 7_8 + 1_8
  end do
  call system_clock(t0, rate)
  dst = src
  call system_clock(t1, rate)
  chk = dst(1) + dst(6250001) + dst(n)
  print '(I0)', chk
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b87_memcopy_big
