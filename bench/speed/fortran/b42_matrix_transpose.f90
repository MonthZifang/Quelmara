! b42_matrix_transpose
program b42_matrix_transpose
  implicit none
  integer(kind=8), parameter :: n = 500_8, sz = n * n
  integer(kind=8) :: a(sz), b(sz)
  integer(kind=8) :: r, c, t0, t1, rate
  do r = 0_8, sz - 1_8
    a(r + 1) = r
  end do
  call system_clock(t0, rate)
  do r = 0_8, n - 1_8
    do c = 0_8, n - 1_8
      b(r * n + c + 1) = a(c * n + r + 1)
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', b(sz)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b42_matrix_transpose
