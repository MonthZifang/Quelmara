! b73_graph_bfs
program b73_graph_bfs
  implicit none
  integer(kind=8), parameter :: n = 1000_8, nn = n * n
  integer(kind=8) :: adj(nn)
  integer(kind=8) :: visited(n), queue(n)
  integer(kind=8) :: seed, e, u, v, front, back, cnt, i, t0, t1, rate
  adj = 0_8
  visited = 0_8
  seed = 55_8
  do e = 0_8, 4999_8
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    u = mod(seed, n)
    seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
    v = mod(seed, n)
    adj(u * n + v + 1) = 1_8
  end do
  call system_clock(t0, rate)
  front = 0_8; back = 0_8
  back = back + 1_8; queue(back) = 0_8; visited(1) = 1_8
  cnt = 0_8
  do while (front < back)
    front = front + 1_8
    u = queue(front)
    cnt = cnt + 1_8
    do v = 0_8, n - 1_8
      if (adj(u * n + v + 1) /= 0_8 .and. visited(v + 1) == 0_8) then
        visited(v + 1) = 1_8; back = back + 1_8; queue(back) = v
      end if
    end do
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b73_graph_bfs
