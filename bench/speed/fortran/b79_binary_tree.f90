! b79_binary_tree
program b79_binary_tree
  implicit none
  integer(kind=8), parameter :: sz = 50000_8
  integer(kind=8) :: keys(sz)
  integer(kind=8) :: n, seed, i, key, pos, j, k, t0, t1, rate
  n = 0_8
  seed = 42_8
  call system_clock(t0, rate)
  do i = 0_8, 49999_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    key = mod(seed, 100000_8)
    pos = n
    do j = 0_8, n - 1_8
      if (keys(j + 1) > key) then
        pos = j; exit
      end if
    end do
    do k = n, pos + 1, -1
      keys(k + 1) = keys(k)
    end do
    keys(pos + 1) = key
    n = n + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', keys(1)
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b79_binary_tree
