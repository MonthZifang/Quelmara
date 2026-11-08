! b85_count_ones
program b85_count_ones
  implicit none
  integer(kind=8) :: i, x, c, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, 4999999_8
    x = i; c = 0_8
    do while (x /= 0_8)
      c = c + iand(x, 1_8); x = ishft(x, -1)
    end do
    acc = acc + c
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b85_count_ones
