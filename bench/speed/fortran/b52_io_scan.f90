! b52_io_scan
program b52_io_scan
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: buf(n)
  integer(kind=8) :: i, sum, t0, t1, rate, j_loop
  do i = 0_8, n - 1_8
    buf(i + 1) = i * 3_8 + 1_8
  end do
  call system_clock(t0, rate)
  sum = 0_8
  do j_loop = 0_8, n - 1_8
    sum = sum + buf(j_loop + 1)
  end do
  call system_clock(t1, rate)
  print '(I0)', sum
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b52_io_scan
