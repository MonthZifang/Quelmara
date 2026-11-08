! b71_sum_squares
program b71_sum_squares
  implicit none
  integer(kind=8) :: i, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 1_8, 1000000_8
    acc = acc + i * i
  end do
  call system_clock(t1, rate)
  print '(I0)', mod(acc, 1000003_8)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b71_sum_squares
