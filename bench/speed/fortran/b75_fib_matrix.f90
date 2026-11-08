! b75_fib_matrix
program b75_fib_matrix
  implicit none
  integer(kind=8) :: a0, a1, a2, a3, n, t, u, v, w, b0, b1, b2, b3, t0, t1, rate
  call system_clock(t0, rate)
  a0 = 1_8; a1 = 1_8; a2 = 1_8; a3 = 0_8
  n = 1000_8
  do while (n > 0_8)
    if (mod(n, 2_8) == 1_8) then
      t = mod(a0 * a1 + a1 * a3, 1000003_8)
      u = mod(a0 * a2 + a1 * a3, 1000003_8)
      v = mod(a2 * a1 + a3 * a3, 1000003_8)
      w = mod(a2 * a1 + a3 * a3, 1000003_8)
      a0 = t; a1 = u; a2 = v; a3 = w
    end if
    b0 = mod(a0 * a0 + a1 * a2, 1000003_8)
    b1 = mod(a0 * a1 + a1 * a3, 1000003_8)
    b2 = mod(a2 * a0 + a3 * a2, 1000003_8)
    b3 = mod(a2 * a1 + a3 * a3, 1000003_8)
    a0 = b0; a1 = b1; a2 = b2; a3 = b3
    n = n / 2_8
  end do
  call system_clock(t1, rate)
  print '(I0)', a1
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b75_fib_matrix
