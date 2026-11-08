! b34_bitops
program b34_bitops
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  acc = 0_8
  call system_clock(t0, rate)
  do i = 0_8, 19999999_8
    acc = acc + (iand(ieor(i, ishft(i, 3)), int(z'FFFF', 8)) + ior(ishft(i, -2), ishft(i, 5)))
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b34_bitops
