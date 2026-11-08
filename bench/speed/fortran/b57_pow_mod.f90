! b57_pow_mod
module b57_mod
  implicit none
contains
  function pow_mod(base, exp, m) result(r)
    integer(kind=8), intent(in) :: base, exp, m
    integer(kind=8) :: r, b, e, rr
    rr = 1_8
    b = mod(base, m)
    e = exp
    do while (e > 0_8)
      if (mod(e, 2_8) == 1_8) rr = mod(rr * b, m)
      b = mod(b * b, m)
      e = e / 2_8
    end do
    r = rr
  end function pow_mod
end module b57_mod

program b57_pow_mod
  use b57_mod
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 1_8, 1000000_8
    acc = mod(acc + pow_mod(i, i, 1000003_8), 1000003_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b57_pow_mod
