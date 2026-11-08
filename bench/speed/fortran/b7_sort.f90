! b7_sort —— 手写快排，20 万个伪随机 int
module b7_mod
  implicit none
contains
  recursive subroutine qsort_i64(a, lo, hi)
    integer(kind=8), intent(inout) :: a(:)
    integer(kind=8), intent(in) :: lo, hi
    integer(kind=8) :: p, i, j, t
    if (lo >= hi) return
    p = a(hi)
    i = lo
    do j = lo, hi - 1
      if (a(j) < p) then
        t = a(i); a(i) = a(j); a(j) = t
        i = i + 1
      end if
    end do
    t = a(i); a(i) = a(hi); a(hi) = t
    call qsort_i64(a, lo, i - 1)
    call qsort_i64(a, i + 1, hi)
  end subroutine qsort_i64
end module b7_mod

program b7_sort
  use b7_mod
  implicit none
  integer(kind=8), parameter :: n = 200000_8
  integer(kind=8) :: v(n)
  integer(kind=8) :: i, x, s, t0, t1, rate
  call system_clock(t0, rate)
  x = 12345_8
  do i = 0_8, n - 1_8
    x = iand(x * 1103515245_8 + 12345_8, 2147483647_8)
    v(i + 1) = x
  end do
  call qsort_i64(v, 1_8, n)
  s = 0_8
  do i = 1_8, n
    s = s + mod(v(i), 1000_8)
  end do
  call system_clock(t1, rate)
  print '(I0)', v(1)
  print '(I0)', v(n)
  print '(I0)', s
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b7_sort
