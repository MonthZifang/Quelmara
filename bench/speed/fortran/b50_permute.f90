! b50_permute
module b50_mod
  implicit none
contains
  recursive function perm(arr, k, nn, acc) result(s)
    integer(kind=8), intent(inout) :: arr(0:)
    integer(kind=8), intent(in) :: k, nn, acc
    integer(kind=8) :: s, i, t, h
    if (k == nn) then
      h = 0_8
      do i = 0_8, nn - 1_8
        h = h * 31_8 + arr(i)
      end do
      s = acc + mod(h, 1000003_8)
      return
    end if
    s = acc
    do i = k, nn - 1_8
      t = arr(k); arr(k) = arr(i); arr(i) = t
      s = perm(arr, k + 1_8, nn, s)
      t = arr(k); arr(k) = arr(i); arr(i) = t
    end do
  end function perm
end module b50_mod

program b50_permute
  use b50_mod
  implicit none
  integer(kind=8) :: ar(0:9)
  integer(kind=8) :: i, r, t0, t1, rate
  do i = 0_8, 9_8
    ar(i) = i + 1_8
  end do
  call system_clock(t0, rate)
  r = perm(ar, 0_8, 10_8, 0_8)
  call system_clock(t1, rate)
  print '(I0)', r
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
end program b50_permute
