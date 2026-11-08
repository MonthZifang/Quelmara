! b61_cache_scan
program b61_cache_scan
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: a(n)
  integer(kind=8) :: acc, j, kk, t0, t1, rate
  do kk = 0_8, n - 1_8
    a(kk + 1) = kk
  end do
  call system_clock(t0, rate)
  acc = 0_8
  do j = 0_8, 9_8
    do kk = 0_8, n - 1_8
      acc = acc + a(kk + 1)
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b61_cache_scan
