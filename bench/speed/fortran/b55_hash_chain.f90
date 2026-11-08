! b55_hash_chain
program b55_hash_chain
  implicit none
  integer(kind=8), parameter :: cap = 262144_8
  integer(kind=8) :: buckets(cap)
  integer(kind=8) :: cnt, j, h, t0, t1, rate
  buckets = 0_8
  call system_clock(t0, rate)
  cnt = 0_8
  do j = 0_8, 199999_8
    h = mod(j * 2654435761_8, cap)
    buckets(h + 1) = buckets(h + 1) + 1_8
    cnt = cnt + 1_8
  end do
  call system_clock(t1, rate)
  print '(I0)', cnt
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b55_hash_chain
