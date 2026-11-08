! b81_bit_reverse
program b81_bit_reverse
  implicit none
  integer(kind=8) :: j, v, r, i, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do j = 0_8, 999999_8
    v = j; r = 0_8
    do i = 0, 31
      r = ishft(r, 1) + iand(v, 1_8)
      v = ishft(v, -1)
    end do
    acc = ieor(acc, r)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b81_bit_reverse
