! b86_matrix_diag
program b86_matrix_diag
  implicit none
  integer(kind=8), parameter :: n = 1000_8, sz = n * n
  integer(kind=8) :: a(sz)
  integer(kind=8) :: i, r, sum, t0, t1, rate
  do i = 0_8, sz - 1_8
    a(i + 1) = mod(i * 7_8 + 3_8, 100_8)
  end do
  call system_clock(t0, rate)
  sum = 0_8
  do r = 0_8, n - 1_8
    sum = sum + a(r * n + r + 1)
  end do
  call system_clock(t1, rate)
  print '(I0)', sum
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b86_matrix_diag
