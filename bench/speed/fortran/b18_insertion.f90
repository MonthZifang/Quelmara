! b18_insertion —— 排序：插入排序 8 万元素
program b18_insertion
  implicit none
  integer(kind=8), parameter :: n = 80000_8
  integer(kind=8) :: a(n)
  integer(kind=8) :: seed, i, x, key, y, chk, t0, t1, rate
  seed = 12345_8
  do i = 0_8, n - 1_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    a(i + 1) = mod(seed, 100000_8)
  end do
  call system_clock(t0, rate)
  do x = 1_8, n - 1_8
    key = a(x + 1)
    y = x - 1
    do while (y >= 0_8 .and. a(y + 1) > key)
      a(y + 2) = a(y + 1)
      y = y - 1
    end do
    a(y + 2) = key
  end do
  call system_clock(t1, rate)
  chk = 0_8
  do i = 1_8, n
    chk = mod(chk + a(i) * i, 1000000007_8)
  end do
  print '(I0)', chk
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b18_insertion
