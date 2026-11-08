! b44_stack_sim
program b44_stack_sim
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: st(n)
  integer(kind=8) :: top, i, t0, t1, rate
  call system_clock(t0, rate)
  top = 0_8
  do i = 0_8, n - 1_8
    st(top + 1) = i
    top = top + 1_8
    if (mod(i, 3_8) == 0_8 .and. top > 0_8) st(top) = st(top) + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', st(top)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b44_stack_sim
