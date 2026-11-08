! b49_floyd
program b49_floyd
  implicit none
  integer(kind=8), parameter :: n = 100_8, sz = n * n
  integer(kind=8) :: dist(sz)
  integer(kind=8) :: seed, e, u, v, w, a, b, c, d1, d2, t0, t1, rate, k_loop
  do e = 0_8, sz - 1_8
    dist(e + 1) = 999999_8
  end do
  do k_loop = 0_8, n - 1_8
    dist(k_loop * n + k_loop + 1) = 0_8
  end do
  seed = 7_8
  do e = 0_8, 299_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    u = mod(seed, n)
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    v = mod(seed, n)
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    w = mod(seed, 100_8) + 1_8
    dist(u * n + v + 1) = w
  end do
  call system_clock(t0, rate)
  do a = 0_8, n - 1_8
    do b = 0_8, n - 1_8
      do c = 0_8, n - 1_8
        d1 = dist(b * n + c + 1)
        d2 = dist(b * n + a + 1) + dist(a * n + c + 1)
        if (d2 < d1) dist(b * n + c + 1) = d2
      end do
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', dist(2)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b49_floyd
