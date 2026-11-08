! b27_sieve —— 埃氏筛 5000 万
program b27_sieve
  implicit none
  integer(kind=8), parameter :: n = 10000000_8
  integer(kind=1) :: c(0:n)
  integer(kind=8) :: p, q, cnt, i, t0, t1, rate
  call system_clock(t0, rate)
  do i = 0_8, n
    c(i) = 1
  end do
  c(0) = 0
  c(1) = 0
  do p = 2_8, n
    if (p * p > n) exit
    if (c(p) /= 0) then
      do q = p * p, n, p
        c(q) = 0
      end do
    end if
  end do
  cnt = 0_8
  do i = 0_8, n
    cnt = cnt + c(i)
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b27_sieve
