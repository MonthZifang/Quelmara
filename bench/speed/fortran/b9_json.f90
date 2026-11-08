! b9_json
program b9_json
  implicit none
  character(len=*), parameter :: DOC = "{""meta"":{""version"":3,""count"":30,""flags"":[1,0,1]},""items"":[{""id"":1,""name"":""user_1"",""score"":37,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n1""},{""id"":2,""name"":""user_2"",""score"":74,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n2""},{""id"":3,""name"":""user_3"",""score"":11,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n3""},{""id"":4,""name"":""user_4"",""score"":48,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n4""},{""id"":5,""name"":""user_5"",""score"":85,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":null},{""id"":6,""name"":""user_6"",""score"":22,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n6""},{""id"":7,""name"":""user_7"",""score"":59,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n7""},{""id"":8,""name"":""user_8"",""score"":96,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n8""},{""id"":9,""name"":""user_9"",""score"":33,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n9""},{""id"":10,""name"":""user_10"",""score"":70,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":null},{""id"":11,""name"":""user_11"",""score"":7,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n11""},{""id"":12,""name"":""user_12"",""score"":44,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n12""},{""id"":13,""name"":""user_13"",""score"":81,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n13""},{""id"":14,""name"":""user_14"",""score"":18,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n14""},{""id"":15,""name"":""user_15"",""score"":55,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":null},{""id"":16,""name"":""user_16"",""score"":92,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n16""},{""id"":17,""name"":""user_17"",""score"":29,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n17""},{""id"":18,""name"":""user_18"",""score"":66,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n18""},{""id"":19,""name"":""user_19"",""score"":3,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n19""},{""id"":20,""name"":""user_20"",""score"":40,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":null},{""id"":21,""name"":""user_21"",""score"":77,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n21""},{""id"":22,""name"":""user_22"",""score"":14,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n22""},{""id"":23,""name"":""user_23"",""score"":51,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n23""},{""id"":24,""name"":""user_24"",""score"":88,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n24""},{""id"":25,""name"":""user_25"",""score"":25,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":null},{""id"":26,""name"":""user_26"",""score"":62,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n26""},{""id"":27,""name"":""user_27"",""score"":99,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n27""},{""id"":28,""name"":""user_28"",""score"":36,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":""n28""},{""id"":29,""name"":""user_29"",""score"":73,""tags"":[""a"",""bb"",""ccc""],""ok"":true,""note"":""n29""},{""id"":30,""name"":""user_30"",""score"":10,""tags"":[""a"",""bb"",""ccc""],""ok"":false,""note"":null}]}"
  integer(kind=8) :: DN, st, total, r
  integer(kind=8) :: t0, t1, rate
  DN = int(len(DOC), 8)
  call system_clock(t0, rate)
  total = 0_8
  do r = 0_8, 1999_8
    st = 0_8
    total = total + jval(DOC, 0_8, st)
  end do
  call system_clock(t1, rate)
  print '(I0)', total
  print *, 'T'
  print '(I0)', (t1 - t0) * 1000000000_8 / rate
contains
  integer(kind=8) function jws(s, p0) result(p)
    character(len=*), intent(in) :: s
    integer(kind=8), intent(in) :: p0
    integer(kind=8) :: c
    p = p0
    do while (p < DN)
      c = int(ichar(s(p + 1:p + 1)), 8)
      if (c == 32_8 .or. c == 9_8 .or. c == 10_8 .or. c == 13_8) then
        p = p + 1_8
      else
        exit
      end if
    end do
  end function jws

  integer(kind=8) function jstr(s, p0) result(p)
    character(len=*), intent(in) :: s
    integer(kind=8), intent(in) :: p0
    p = p0 + 1_8
    do while (p < DN)
      if (s(p + 1:p + 1) == '"') exit
      p = p + 1_8
    end do
    p = p + 1_8
  end function jstr

  integer(kind=8) function jnum(s, p0, st) result(v)
    character(len=*), intent(in) :: s
    integer(kind=8), intent(in) :: p0
    integer(kind=8), intent(out) :: st
    integer(kind=8) :: p, c, neg
    p = p0; v = 0_8; neg = 0_8
    if (p < DN .and. s(p + 1:p + 1) == "-") then
      neg = 1_8; p = p + 1_8
    end if
    do while (p < DN)
      c = int(ichar(s(p + 1:p + 1)), 8)
      if (c >= 48_8 .and. c <= 57_8) then
        v = v * 10_8 + (c - 48_8); p = p + 1_8
      else
        exit
      end if
    end do
    if (neg /= 0_8) v = -v
    st = p
  end function jnum

  recursive integer(kind=8) function jval(s, p0, st) result(acc)
    character(len=*), intent(in) :: s
    integer(kind=8), intent(in) :: p0
    integer(kind=8), intent(out) :: st
    integer(kind=8) :: p, c, q
    p = jws(s, p0)
    if (p >= DN) then
      st = p; acc = 0_8; return
    end if
    c = int(ichar(s(p + 1:p + 1)), 8)
    if (c == 123_8) then
      q = jws(s, p + 1_8); acc = 0_8
      if (q < DN .and. s(q + 1:q + 1) == "}") then
        st = q + 1_8; return
      end if
      do
        q = jws(s, q)
        q = jstr(s, q)
        q = jws(s, q)
        q = q + 1_8
        acc = acc + jval(s, q, st)
        q = jws(s, st)
        if (q < DN .and. s(q + 1:q + 1) == ",") then
          q = q + 1_8
        else
          exit
        end if
      end do
      st = q + 1_8; return
    end if
    if (c == 91_8) then
      q = jws(s, p + 1_8); acc = 0_8
      if (q < DN .and. s(q + 1:q + 1) == "]") then
        st = q + 1_8; return
      end if
      do
        acc = acc + jval(s, q, st)
        q = jws(s, st)
        if (q < DN .and. s(q + 1:q + 1) == ",") then
          q = q + 1_8
        else
          exit
        end if
      end do
      st = q + 1_8; return
    end if
    if (c == 34_8) then
      st = jstr(s, p); acc = 0_8; return
    end if
    if (c == 45_8 .or. (c >= 48_8 .and. c <= 57_8)) then
      acc = jnum(s, p, st); return
    end if
    q = p
    do while (q < DN)
      c = int(ichar(s(q + 1:q + 1)), 8)
      if (c >= 97_8 .and. c <= 122_8) then
        q = q + 1_8
      else
        exit
      end if
    end do
    st = q; acc = 0_8
  end function jval
end program b9_json
