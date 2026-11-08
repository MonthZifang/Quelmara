! b8_threads1
program b8_threads1
  implicit none
  integer(kind=8) :: r, i, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, 159999999_8
    acc = acc + mod(i * 7_8, 13_8)
  end do
  r = acc
  call system_clock(t1, rate)
  print '(I0)', r
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b8_threads1
