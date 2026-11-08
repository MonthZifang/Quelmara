! b74_accum_poly
program b74_accum_poly
  implicit none
  integer(kind=8) :: n, k, s, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do n = 1_8, 5000000_8
    s = 0_8
    do k = 0, 4
      s = s * n + int(k, 8) * 3_8 + 1_8
    end do
    acc = acc + mod(s, 1000003_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', mod(acc, 1000003_8)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b74_accum_poly
