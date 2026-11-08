! b56_sieve_opt
program b56_sieve_opt
  implicit none
  integer(kind=8), parameter :: n = 2000000_8
  integer(kind=8) :: flags(0:n)
  integer(kind=8) :: p, q, cnt, kk, t0, t1, rate
  do kk = 0_8, n
    flags(kk) = 1_8
  end do
  flags(0) = 0_8; flags(1) = 0_8
  call system_clock(t0, rate)
  do p = 2_8, n
    if (p * p > n) exit
    if (flags(p) /= 0_8) then
      q = p * p
      do while (q <= n)
        flags(q) = 0_8
        q = q + p
      end do
    end if
  end do
  cnt = 0_8
  do kk = 2_8, n
    if (flags(kk) /= 0_8) cnt = cnt + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b56_sieve_opt
