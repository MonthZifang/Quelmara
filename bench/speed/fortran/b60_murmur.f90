! b60_murmur
program b60_murmur
  implicit none
  integer(kind=8) :: h, k, i, t0, t1, rate
  integer(kind=8), parameter :: c = -862048943_8
  integer(kind=8), parameter :: mask45 = int(z'1FFFFFFFFFFF', 8)
  call system_clock(t0, rate)
  h = 0_8
  do i = 0_8, 999999_8
    k = i
    k = k * c
    k = ior(ishft(k, 13), iand(ashr(k, 51_8), mask45))
    k = k * c
    h = ieor(h, k)
    h = ior(ishft(h, 13), iand(ashr(h, 51_8), mask45))
    h = h * 5_8 + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', h
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
contains
  integer(kind=8) function ashr(x, s)
    integer(kind=8), intent(in) :: x, s
    integer(kind=8) :: p
    p = ishft(1_8, int(s))
    if (x < 0_8) then
      ashr = -((-x + p - 1_8) / p)
    else
      ashr = x / p
    end if
  end function ashr
end program b60_murmur
