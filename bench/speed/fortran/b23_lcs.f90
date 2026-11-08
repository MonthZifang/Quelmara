! b23_lcs —— DP：最长公共子序列 1500×1500
program b23_lcs
  implicit none
  integer(kind=8), parameter :: n = 1500_8
  integer(kind=8) :: prev(0:n), cur(0:n)
  integer(kind=8) :: r, c, av, bv, t0, t1, rate
  call system_clock(t0, rate)
  prev = 0_8
  cur = 0_8
  do r = 1_8, n
    do c = 1_8, n
      av = mod(r * 7_8 + 3_8, 4_8)
      bv = mod(c * 11_8 + 5_8, 4_8)
      if (av == bv) then
        cur(c) = prev(c - 1) + 1_8
      else if (prev(c) > cur(c - 1)) then
        cur(c) = prev(c)
      else
        cur(c) = cur(c - 1)
      end if
    end do
    do c = 0_8, n
      prev(c) = cur(c)
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', prev(n)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b23_lcs
