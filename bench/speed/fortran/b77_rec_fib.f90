! b77_rec_fib
module b77_mod
  implicit none
contains
  recursive function fib(n) result(r)
    integer(kind=8), intent(in) :: n
    integer(kind=8) :: r
    if (n <= 1_8) then
      r = n
    else
      r = fib(n - 1_8) + fib(n - 2_8)
    end if
  end function fib
end module b77_mod

program b77_rec_fib
  use b77_mod
  implicit none
  integer(kind=8) :: r, t0, t1, rate
  call system_clock(t0, rate)
  r = fib(25_8)
  call system_clock(t1, rate)
  print '(I0)', r
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b77_rec_fib
