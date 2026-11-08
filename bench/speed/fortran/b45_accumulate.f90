! b45_accumulate
program b45_accumulate
  implicit none
  integer(kind=8) :: acc, n, s, k, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do n = 1_8, 1000000_8
    s = 0_8
    do k = 0_8, 9_8
      s = s * n + k
    end do
    acc = acc + mod(s, 1000003_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b45_accumulate
