! b12_gcd —— 整数：3000 万次辗转相除
module gcd_mod
  implicit none
contains
  function gcd(a, b) result(g)
    integer(kind=8), intent(in) :: a, b
    integer(kind=8) :: g, x, y, t
    x = a
    y = b
    do while (y /= 0)
      t = y
      y = mod(x, y)
      x = t
    end do
    g = x
  end function gcd
end module gcd_mod

program b12_gcd
  use gcd_mod
  implicit none
  integer(kind=8) :: n, s, i, t0, t1, rate
  n = 30000000_8
  call system_clock(t0, rate)
  s = 0
  do i = 1_8, n
    s = s + gcd(i, 1000000_8 - i)
  end do
  call system_clock(t1, rate)
  print *, s
  print *, 'T'
  print *, (t1 - t0) * 1000000000_8 / rate
end program b12_gcd
