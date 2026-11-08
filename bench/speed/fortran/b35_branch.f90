! b35_branch
program b35_branch
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  acc = 0_8
  call system_clock(t0, rate)
  do i = 0_8, 19999999_8
    if (iand(i, 3_8) == 0_8) then
      acc = acc + 1_8
    else
      acc = acc - 1_8
    end if
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b35_branch
