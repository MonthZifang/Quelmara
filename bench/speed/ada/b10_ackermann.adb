-- b10_ackermann —— Ackermann(2,8)
with Ada.Text_IO;       use Ada.Text_IO;
with Ada.Real_Time;     use Ada.Real_Time;
with Ada.Strings;       use Ada.Strings;
with Ada.Strings.Fixed; use Ada.Strings.Fixed;

procedure B10_Ackermann is
   subtype LLI is Long_Long_Integer;
   T0, T1 : Time;

   function Ack (M, N : LLI) return LLI is
   begin
      if M = 0 then return N + 1; end if;
      if N = 0 then return Ack (M - 1, 1); end if;
      return Ack (M - 1, Ack (M, N - 1));
   end Ack;

   R : LLI;
begin
   T0 := Clock;
   R := Ack (2, 8);
   T1 := Clock;
   Put_Line (Trim (LLI'Image (R), Left));
   Put_Line ("T");
   Put_Line (Trim (LLI'Image (LLI (To_Duration (T1 - T0) * 1_000_000_000.0)), Left));
end B10_Ackermann;
