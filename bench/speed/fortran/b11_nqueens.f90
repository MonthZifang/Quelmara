! b11_nqueens —— N 皇后(8)：回溯 + 数组标记
module b11_mod
  implicit none
contains
  recursive function solve(col, n, r) result(cnt)
    integer(kind=8), intent(inout) :: col(0:)
    integer(kind=8), intent(in) :: n, r
    integer(kind=8) :: cnt
    integer(kind=8) :: c, k, cc, d, ok
    if (r == n) then
      cnt = 1_8
      return
    end if
    cnt = 0_8
    do c = 0_8, n - 1_8
      ok = 1_8
      do k = 0_8, r - 1_8
        cc = col(k)
        if (cc == c) ok = 0_8
        d = cc - c
        if (d == k - r .or. d == r - k) ok = 0_8
      end do
      if (ok == 1_8) then
        col(r) = c
        cnt = cnt + solve(col, n, r + 1_8)
      end if
    end do
  end function solve
end module b11_mod

program b11_nqueens
  use b11_mod
  implicit none
  integer(kind=8) :: n, col(0:7), total, rep, t0, t1, rate
  n = 8_8
  col = 0_8
  call system_clock(t0, rate)
  total = 0_8
  do rep = 0_8, 1999_8
    total = total + solve(col, n, 0_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', total
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b11_nqueens
