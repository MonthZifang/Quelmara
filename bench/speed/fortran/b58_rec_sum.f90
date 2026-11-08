! b58_rec_sum
module b58_mod
  implicit none
contains
  recursive function rec_sum(n) result(r)
    integer(kind=8), intent(in) :: n
    integer(kind=8) :: r
    if (n <= 0_8) then
      r = 0_8
    else
      r = n + rec_sum(n - 1_8)
    end if
  end function rec_sum
end module b58_mod

program b58_rec_sum
  use b58_mod
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 1_8, 100_8
    acc = acc + rec_sum(10000_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b58_rec_sum
