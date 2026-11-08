! b62_pred_branch
program b62_pred_branch
  implicit none
  integer(kind=8) :: acc, i, t0, t1, rate
  call system_clock(t0, rate)
  acc = 0_8
  do i = 0_8, 4999999_8
    if (mod(i * 7_8 + 3_8, 5_8) < 2_8) then
      acc = acc + 1_8
    else
      acc = acc - 1_8
    end if
  end do
  call system_clock(t1, rate)
  print '(I0)', acc
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b62_pred_branch
