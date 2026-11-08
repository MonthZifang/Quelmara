! b70_lin_search
program b70_lin_search
  implicit none
  integer(kind=8), parameter :: n = 1000_8
  integer(kind=8) :: a(n)
  integer(kind=8) :: i, j, k, target, found, t0, t1, rate
  do i = 0_8, n - 1_8
    a(i + 1) = i * 3_8 + 7_8
  end do
  call system_clock(t0, rate)
  found = 0_8
  do j = 0_8, 999999_8
    target = mod(j * 37_8 + 11_8, 3000_8)
    do k = 0_8, n - 1_8
      if (a(k + 1) == target) found = found + 1_8
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', found
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b70_lin_search
