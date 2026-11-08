! b10_ackermann —— Ackermann(2,8)：深层非原始递归
module b10_mod
  implicit none
contains
  recursive function ack(m, n) result(r)
    integer(kind=8), intent(in) :: m, n
    integer(kind=8) :: r
    if (m == 0_8) then
      r = n + 1_8
    else if (n == 0_8) then
      r = ack(m - 1_8, 1_8)
    else
      r = ack(m - 1_8, ack(m, n - 1_8))
    end if
  end function ack
end module b10_mod

program b10_ackermann
  use b10_mod
  implicit none
  integer(kind=8) :: t0, t1, rate
  call system_clock(t0, rate)
  print '(I0)', ack(2_8, 8_8)
  call system_clock(t1, rate)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b10_ackermann
