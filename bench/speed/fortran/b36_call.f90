! b36_call
module b36_mod
  implicit none
contains
  function add3(a, b, c) result(r)
    integer(kind=8), intent(in) :: a, b, c
    integer(kind=8) :: r
    r = a + b + c
  end function add3
end module b36_mod

program b36_call
  use b36_mod
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  ! v4.115 fairness audit: volatile input stops whole-loop compile-time folding.
  integer(kind=8), volatile :: n
  n = 10000000_8
  acc = 0_8
  call system_clock(t0, rate)
  do i = 0_8, n - 1_8
    acc = add3(acc, i, 1_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b36_call
