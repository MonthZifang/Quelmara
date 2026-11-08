-- b1_int —— 整数运算热循环，20M 次
with Ada.Text_IO;       use Ada.Text_IO;
with Ada.Real_Time;     use Ada.Real_Time;
with Ada.Strings;       use Ada.Strings;
with Ada.Strings.Fixed; use Ada.Strings.Fixed;

procedure B1_Int is
   subtype LLI is Long_Long_Integer;
   T0, T1 : Time;
   N  : constant LLI := 20000000;
   Acc : LLI := 0;
begin
   T0 := Clock;
   for I in 0 .. N - 1 loop
      Acc := Acc + (I * 7) mod 13;
   end loop;
   T1 := Clock;
   Put_Line (Trim (LLI'Image (Acc), Left));
   Put_Line ("T");
   Put_Line (Trim (LLI'Image (LLI (To_Duration (T1 - T0) * 1_000_000_000.0)), Left));
end B1_Int;
