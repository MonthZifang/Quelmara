! b6_hash —— 手写开放寻址哈希表，10 万插入 + 10 万查找
program b6_hash
  implicit none
  integer(kind=8), parameter :: cap = 1048576_8, mask = cap - 1_8
  integer(kind=8), parameter :: n = 300000_8
  integer(kind=8) :: kt(cap), vt(cap)
  integer(kind=8) :: i, k, h, s, t0, t1, rate
  kt = 0_8
  vt = 0_8
  call system_clock(t0, rate)
  do i = 1_8, n
    k = i * 3_8 + 1_8
    h = iand(k * 2654435761_8, mask)
    do while (kt(h + 1) /= 0_8)
      h = iand(h + 1_8, mask)
    end do
    kt(h + 1) = k
    vt(h + 1) = k * 2_8
  end do
  s = 0_8
  do i = 1_8, n
    k = i * 3_8 + 1_8
    h = iand(k * 2654435761_8, mask)
    do while (kt(h + 1) /= k)
      h = iand(h + 1_8, mask)
    end do
    s = s + vt(h + 1)
  end do
  call system_clock(t1, rate)
  print '(I0)', s
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b6_hash
