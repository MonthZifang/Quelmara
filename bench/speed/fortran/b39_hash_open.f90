! b39_hash_open
program b39_hash_open
  implicit none
  integer(kind=8), parameter :: cap = 1048576_8
  integer(kind=8) :: keys(cap), vals(cap)
  integer(kind=8) :: j, k, h, found, t0, t1, rate
  keys = 0_8
  vals = 0_8
  call system_clock(t0, rate)
  do j = 0_8, 499999_8
    h = mod(j * 2654435761_8, cap)
    keys(h + 1) = j
    vals(h + 1) = j * 2_8
  end do
  found = 0_8
  do k = 0_8, 499999_8
    h = mod(k * 2654435761_8, cap)
    if (keys(h + 1) == k) found = found + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', found
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b39_hash_open
