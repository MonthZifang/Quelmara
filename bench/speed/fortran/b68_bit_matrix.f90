! b68_bit_matrix
program b68_bit_matrix
  implicit none
  integer(kind=8), parameter :: n = 256_8, sz = n * n
  integer(kind=8) :: a(sz), b(sz)
  integer(kind=8) :: i, r, c, t0, t1, rate
  do i = 0_8, sz - 1_8
    a(i + 1) = mod(i, 2_8)
  end do
  call system_clock(t0, rate)
  do r = 0_8, n - 1_8
    do c = 0_8, n - 1_8
      b(r * n + c + 1) = a(c * n + (n - 1_8 - r) + 1)
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', b(1)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b68_bit_matrix
