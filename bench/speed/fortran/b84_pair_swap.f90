! b84_pair_swap
program b84_pair_swap
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: keys(n), vals(n)
  integer(kind=8) :: i, j, k, v, t0, t1, rate
  do i = 0_8, n - 1_8
    keys(i + 1) = i
    vals(i + 1) = i * 2_8
  end do
  call system_clock(t0, rate)
  do j = 0_8, n - 1_8
    k = keys(j + 1); v = vals(j + 1)
    keys(j + 1) = v; vals(j + 1) = k
  end do
  call system_clock(t1, rate)
  print '(I0)', keys(1) + vals(1)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b84_pair_swap
