! b47_bitcount
module b47_mod
  implicit none
contains
  function popcount(x) result(c)
    integer(kind=8), intent(in) :: x
    integer(kind=8) :: c, y
    c = 0_8
    y = x
    do while (y /= 0_8)
      c = c + iand(y, 1_8)
      y = ishft(y, -1)
    end do
  end function popcount
end module b47_mod

program b47_bitcount
  use b47_mod
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, 9999999_8
    acc = acc + popcount(i)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b47_bitcount
