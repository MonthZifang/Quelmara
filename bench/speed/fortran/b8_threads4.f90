! b8_threads4
program b8_threads4
  implicit none
  integer(kind=8) :: k, i, acc, total, t0, t1, rate
  call system_clock(t0, rate)
  total = 0_8
  do k = 0, 3
    acc = 0_8
    do i = 0_8, 39999999_8
      acc = acc + mod(i * 7_8, 13_8)
    end do
    total = total + acc
  end do
  call system_clock(t1, rate)
  print '(I0)', total
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b8_threads4
