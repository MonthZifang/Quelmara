! b59_mat_vec
program b59_mat_vec
  implicit none
  integer(kind=8), parameter :: n = 500_8, sz = n * n
  integer(kind=8) :: mat(sz), vec(n)
  integer(kind=8) :: r, c, total, s, t0, t1, rate
  do r = 0_8, sz - 1_8
    mat(r + 1) = mod(r * 7_8 + 3_8, 100_8)
  end do
  do c = 0_8, n - 1_8
    vec(c + 1) = mod(c * 13_8 + 1_8, 100_8)
  end do
  call system_clock(t0, rate)
  total = 0_8
  do r = 0_8, n - 1_8
    s = 0_8
    do c = 0_8, n - 1_8
      s = s + mat(r * n + c + 1) * vec(c + 1)
    end do
    total = total + s
  end do
  call system_clock(t1, rate)
  print '(I0)', total
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b59_mat_vec
