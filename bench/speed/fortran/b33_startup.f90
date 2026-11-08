! b33_startup
module b33_mod
  implicit none
contains
  function init() result(s)
    integer(kind=8) :: s, i
    s = 0_8
    do i = 0_8, 999_8
      s = s + i
    end do
  end function init
end module b33_mod

program b33_startup
  use b33_mod
  implicit none
  integer(kind=8) :: a, b, c, d, t0, t1, rate
  call system_clock(t0, rate)
  a = init(); b = init(); c = init(); d = init()
  call system_clock(t1, rate)
  print '(I0)', a + b + c + d
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b33_startup
