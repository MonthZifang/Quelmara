! b3_recursion —— 朴素递归 fib(30)
module b3_mod
  implicit none
contains
  recursive function fib(n) result(r)
    integer(kind=8), intent(in) :: n
    integer(kind=8) :: r
    if (n < 2_8) then
      r = n
    else
      r = fib(n - 1_8) + fib(n - 2_8)
    end if
  end function fib
end module b3_mod

program b3_recursion
  use b3_mod
  implicit none
  integer(kind=8) :: t0, t1, rate
  call system_clock(t0, rate)
  print '(I0)', fib(30_8)
  call system_clock(t1, rate)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b3_recursion
