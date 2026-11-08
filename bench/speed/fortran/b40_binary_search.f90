! b40_binary_search
module b40_mod
  implicit none
contains
  function bsearch_impl(a, n, target) result(r)
    integer(kind=8), intent(in) :: a(:), n, target
    integer(kind=8) :: r, lo, hi, mid
    lo = 0_8; hi = n - 1_8
    do while (lo <= hi)
      mid = (lo + hi) / 2_8
      if (a(mid + 1) == target) then
        r = mid
        return
      end if
      if (a(mid + 1) < target) then
        lo = mid + 1_8
      else
        hi = mid - 1_8
      end if
    end do
    r = -1_8
  end function bsearch_impl
end module b40_mod

program b40_binary_search
  use b40_mod
  implicit none
  integer(kind=8), parameter :: n = 1000000_8
  integer(kind=8) :: a(n)
  integer(kind=8) :: j, found, t0, t1, rate
  do j = 0_8, n - 1_8
    a(j + 1) = j * 2_8
  end do
  call system_clock(t0, rate)
  found = 0_8
  do j = 0_8, 999999_8
    if (bsearch_impl(a, n, j * 2_8) >= 0_8) found = found + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', found
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b40_binary_search
