! b53_thread_sim (replicate deterministic result without real threads)
module b53_mod
  implicit none
contains
  function work(start, end_) result(s)
    integer(kind=8), intent(in) :: start, end_
    integer(kind=8) :: s, i
    s = 0_8
    do i = start, end_ - 1_8
      s = s + i * 2_8 + 1_8
    end do
  end function work
end module b53_mod

program b53_thread_sim
  use b53_mod
  implicit none
  integer(kind=8) :: a, b, c, d, t0, t1, rate
  ! v4.115 fairness audit: volatile input stops whole-workload compile-time folding.
  integer(kind=8), volatile :: n
  n = 10000000_8
  call system_clock(t0, rate)
  a = work(0_8, n / 4_8)
  b = work(n / 4_8, n / 2_8)
  c = work(n / 2_8, 3_8 * n / 4_8)
  d = work(3_8 * n / 4_8, n)
  call system_clock(t1, rate)
  print '(I0)', a + b + c + d
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b53_thread_sim
