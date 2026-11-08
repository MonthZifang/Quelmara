! b4_array —— 数组写入 + 顺序遍历 + 跨步遍历（200 万元素）
program b4_array
  implicit none
  integer(kind=8), parameter :: n = 2000000_8
  integer(kind=8) :: v(n)
  integer(kind=8) :: i, s, t, t0, t1, rate
  call system_clock(t0, rate)
  do i = 0_8, n - 1_8
    v(i + 1) = i * 3_8 + 1_8
  end do
  s = 0_8
  do i = 0_8, n - 1_8
    s = s + v(i + 1)
  end do
  t = 0_8
  do i = 0_8, n - 1_8, 7_8
    t = t + v(i + 1)
  end do
  call system_clock(t1, rate)
  print '(I0)', s
  print '(I0)', t
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b4_array
