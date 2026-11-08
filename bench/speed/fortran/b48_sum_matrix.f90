! b48_sum_matrix
program b48_sum_matrix
  implicit none
  integer(kind=8), parameter :: n = 500_8, sz = n * n
  integer(kind=8) :: a(sz)
  integer(kind=8) :: r, c, total, s, t0, t1, rate
  do r = 0_8, sz - 1_8
    a(r + 1) = r
  end do
  call system_clock(t0, rate)
  total = 0_8
  do r = 0_8, n - 1_8
    s = 0_8
    do c = 0_8, n - 1_8
      s = s + a(r * n + c + 1)
    end do
    total = total + s
  end do
  call system_clock(t1, rate)
  print '(I0)', total
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b48_sum_matrix
