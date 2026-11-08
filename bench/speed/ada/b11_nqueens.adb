-- b11_nqueens —— N 皇后(8)：回溯 + 数组标记
with Ada.Text_IO;       use Ada.Text_IO;
with Ada.Real_Time;     use Ada.Real_Time;
with Ada.Strings;       use Ada.Strings;
with Ada.Strings.Fixed; use Ada.Strings.Fixed;

procedure B11_Nqueens is
   subtype LLI is Long_Long_Integer;
   T0, T1 : Time;
   Col : array (LLI range 0 .. 7) of LLI := (others => 0);
   Total : LLI := 0;

   function Solve (N, R : LLI) return LLI is
      Cnt : LLI := 0;
      Ok  : LLI;
   begin
      if R = N then return 1; end if;
      for C in 0 .. N - 1 loop
         Ok := 1;
         for K in 0 .. R - 1 loop
            declare
               Cc : LLI := Col (K);
               D  : LLI;
            begin
               if Cc = C then Ok := 0; end if;
               D := Cc - C;
               if D = K - R or else D = R - K then Ok := 0; end if;
            end;
         end loop;
         if Ok = 1 then
            Col (R) := C;
            Cnt := Cnt + Solve (N, R + 1);
         end if;
      end loop;
      return Cnt;
   end Solve;

begin
   T0 := Clock;
   for Rep in 0 .. 1999 loop
      Total := Total + Solve (8, 0);
   end loop;
   T1 := Clock;
   Put_Line (Trim (LLI'Image (Total), Left));
   Put_Line ("T");
   Put_Line (Trim (LLI'Image (LLI (To_Duration (T1 - T0) * 1_000_000_000.0)), Left));
end B11_Nqueens;
