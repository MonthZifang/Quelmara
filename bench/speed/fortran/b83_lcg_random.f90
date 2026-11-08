! b83_lcg_random
program b83_lcg_random
  implicit none
  integer(kind=8) :: seed, i, acc, t0, t1, rate
  call system_clock(t0, rate)
  seed = 12345_8
  acc = 0_8
  do i = 0_8, 9999999_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    acc = acc + mod(seed, 100_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b83_lcg_random
