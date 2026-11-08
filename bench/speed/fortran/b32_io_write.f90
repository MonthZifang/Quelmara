! b32_io_write
program b32_io_write
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: buf(n)
  integer(kind=8) :: i, t0, t1, rate
  call system_clock(t0, rate)
  do i = 0_8, n - 1_8
    buf(i + 1) = i * 2_8 + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', buf(n)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b32_io_write
