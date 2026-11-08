! b13_collatz —— Collatz 序列长度累加(1..30万)
module b13_mod
  implicit none
contains
  function clen(n) result(c)
    integer(kind=8), intent(in) :: n
    integer(kind=8) :: c, m
    m = n
    c = 0_8
    do while (m /= 1_8)
      if (mod(m, 2_8) == 0_8) then
        m = m / 2_8
      else
        m = 3_8 * m + 1_8
      end if
      c = c + 1_8
    end do
  end function clen
end module b13_mod

program b13_collatz
  use b13_mod
  implicit none
  integer(kind=8) :: best, bn, i, c, t0, t1, rate
  call system_clock(t0, rate)
  best = 0_8; bn = 0_8
  do i = 1_8, 300000_8
    c = clen(i)
    if (c > best) then
      best = c; bn = i
    end if
  end do
  call system_clock(t1, rate)
  print '(I0)', best * 10000000_8 + bn
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b13_collatz
