! b43_gcd_lcm
program b43_gcd_lcm
  implicit none
  integer(kind=8) :: a, b, t, acc, i, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 1_8, 1000000_8
    a = i; b = 1000000_8 - i + 1_8
    do while (b /= 0_8)
      t = b; b = mod(a, b); a = t
    end do
    acc = acc + a
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b43_gcd_lcm
