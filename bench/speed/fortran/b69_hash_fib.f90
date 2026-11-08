! b69_hash_fib
program b69_hash_fib
  implicit none
  integer(kind=8), parameter :: cap = 524288_8
  integer(kind=8) :: tab(cap)
  integer(kind=8) :: j, h, cnt, t0, t1, rate
  tab = 0_8
  call system_clock(t0, rate)
  cnt = 0_8
  do j = 0_8, 499999_8
    h = mod(mod(j * 2654435761_8, cap) + cap, cap)
    tab(h + 1) = tab(h + 1) + 1_8
    cnt = cnt + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b69_hash_fib
