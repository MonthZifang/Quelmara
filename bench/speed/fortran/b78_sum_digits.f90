! b78_sum_digits
program b78_sum_digits
  implicit none
  integer(kind=8) :: i, n, s, acc, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, 999999_8
    n = i; s = 0_8
    do while (n > 0_8)
      s = s + mod(n, 10_8); n = n / 10_8
    end do
    acc = acc + s
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b78_sum_digits
