! b67_bubble_opt
program b67_bubble_opt
  implicit none
  integer(kind=8), parameter :: n = 5000_8
  integer(kind=8) :: a(n)
  integer(kind=8) :: seed, i, j, t, swapped, t0, t1, rate
  seed = 99_8
  do i = 0_8, n - 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    a(i + 1) = mod(seed, 100000_8)
  end do
  call system_clock(t0, rate)
  swapped = 1_8
  do while (swapped /= 0_8)
    swapped = 0_8
    do j = 0_8, n - 2_8
      if (a(j + 1) > a(j + 2)) then
        t = a(j + 1); a(j + 1) = a(j + 2); a(j + 2) = t; swapped = 1_8
      end if
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', a(1)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b67_bubble_opt
