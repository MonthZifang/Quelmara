! b65_random_walk
program b65_random_walk
  implicit none
  integer(kind=8) :: x, y, seed, d, i, t0, t1, rate
  call system_clock(t0, rate)
  x = 0_8; y = 0_8
  seed = 12345_8
  do i = 0_8, 1999999_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    d = mod(seed, 4_8)
    if (d == 0_8) then
      x = x + 1_8
    else if (d == 1_8) then
      x = x - 1_8
    else if (d == 2_8) then
      y = y + 1_8
    else
      y = y - 1_8
    end if
  end do
  call system_clock(t1, rate)
  print '(I0)', x * 1000000_8 + y
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b65_random_walk
