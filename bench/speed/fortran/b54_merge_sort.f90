! b54_merge_sort
module b54_mod
  implicit none
contains
  recursive subroutine msort(a, lo, hi, tmp)
    integer(kind=8), intent(inout) :: a(:), tmp(:)
    integer(kind=8), intent(in) :: lo, hi
    integer(kind=8) :: mid, i, j, k, x_loop
    if (hi - lo <= 1_8) return
    mid = (lo + hi) / 2_8
    call msort(a, lo, mid, tmp)
    call msort(a, mid, hi, tmp)
    i = lo; j = mid; k = 0_8
    do while (i < mid .and. j < hi)
      if (a(i + 1) <= a(j + 1)) then
        tmp(k + 1) = a(i + 1); i = i + 1_8
      else
        tmp(k + 1) = a(j + 1); j = j + 1_8
      end if
      k = k + 1_8
    end do
    do while (i < mid)
      tmp(k + 1) = a(i + 1); i = i + 1_8; k = k + 1_8
    end do
    do while (j < hi)
      tmp(k + 1) = a(j + 1); j = j + 1_8; k = k + 1_8
    end do
    do x_loop = 0_8, k - 1_8
      a(lo + x_loop + 1) = tmp(x_loop + 1)
    end do
  end subroutine msort
end module b54_mod

program b54_merge_sort
  use b54_mod
  implicit none
  integer(kind=8), parameter :: n = 100000_8
  integer(kind=8) :: a(n), tmp(n)
  integer(kind=8) :: seed, i, t0, t1, rate
  seed = 12345_8
  do i = 0_8, n - 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    a(i + 1) = mod(seed, 1000000_8)
  end do
  call system_clock(t0, rate)
  call msort(a, 0_8, n, tmp)
  call system_clock(t1, rate)
  print '(I0)', a(1)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b54_merge_sort
