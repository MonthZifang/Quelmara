! b28_matrix —— 数值：矩阵乘法 300x300
program b28_matrix
  implicit none
  integer(kind=8), parameter :: n = 300
  integer(kind=8) :: a(n,n), b(n,n), c(n,n)
  integer(kind=8) :: i, j, k, chk, t0, t1, rate
  integer(kind=8) :: seed
  seed = 7_8
  do i = 1_8, n
    do j = 1_8, n
      seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
      a(i,j) = mod(seed, 100_8)
      seed = mod(seed * 1103515245_8 + 12345_8, 2147483648_8)
      b(i,j) = mod(seed, 100_8)
      c(i,j) = 0_8
    end do
  end do
  call system_clock(t0, rate)
  do i = 1_8, n
    do k = 1_8, n
      do j = 1_8, n
        c(i,j) = c(i,j) + a(i,k) * b(k,j)
      end do
    end do
  end do
  call system_clock(t1, rate)
  chk = 0_8
  do i = 1_8, n
    do j = 1_8, n
      chk = mod(chk + c(i,j), 1000000007_8)
    end do
  end do
  print *, chk
  print *, 'T'
  print *, (t1 - t0) * 1000000000_8 / rate
end program b28_matrix
