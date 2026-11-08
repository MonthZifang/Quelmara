! b38_prime
module b38_mod
  implicit none
contains
  function is_prime(n) result(r)
    integer(kind=8), intent(in) :: n
    integer(kind=8) :: d
    integer :: r
    if (n < 2_8) then
      r = 0
    else if (n == 2_8) then
      r = 1
    else if (mod(n, 2_8) == 0_8) then
      r = 0
    else
      r = 1
      d = 3_8
      do while (d * d <= n)
        if (mod(n, d) == 0_8) then
          r = 0
          return
        end if
        d = d + 2_8
      end do
    end if
  end function is_prime
end module b38_mod

program b38_prime
  use b38_mod
  implicit none
  integer(kind=8) :: cnt, i, t0, t1, rate
  cnt = 0_8
  call system_clock(t0, rate)
  do i = 0_8, 99999_8
    cnt = cnt + is_prime(i)
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b38_prime
