-- b3_recursion —— 朴素递归 fib(30)
with Ada.Text_IO;       use Ada.Text_IO;
with Ada.Real_Time;     use Ada.Real_Time;
with Ada.Strings;       use Ada.Strings;
with Ada.Strings.Fixed; use Ada.Strings.Fixed;

procedure B3_Recursion is
   subtype LLI is Long_Long_Integer;
   T0, T1 : Time;

   function Fib (N : LLI) return LLI is
   begin
      if N < 2 then return N; end if;
      return Fib (N - 1) + Fib (N - 2);
   end Fib;

   R : LLI;
begin
   T0 := Clock;
   R := Fib (30);
   T1 := Clock;
   Put_Line (Trim (LLI'Image (R), Left));
   Put_Line ("T");
   Put_Line (Trim (LLI'Image (LLI (To_Duration (T1 - T0) * 1_000_000_000.0)), Left));
end B3_Recursion;
