-- b12_gcd —— 整数：3000 万次辗转相除
with Ada.Text_IO; use Ada.Text_IO;
with Ada.Integer_Text_IO; use Ada.Integer_Text_IO;
with Ada.Real_Time; use Ada.Real_Time;

procedure B12_GCD is
   function GCD (A, B : Long_Long_Integer) return Long_Long_Integer is
      X : Long_Long_Integer := A;
      Y : Long_Long_Integer := B;
      T : Long_Long_Integer;
   begin
      while Y /= 0 loop
         T := Y;
         Y := X mod Y;
         X := T;
      end loop;
      return X;
   end GCD;

   N : constant Long_Long_Integer := 30000000;
   S : Long_Long_Integer := 0;
   T0, T1 : Time;
begin
   T0 := Clock;
   for I in 1 .. N loop
      S := S + GCD (I, 1000000 - I);
   end loop;
   T1 := Clock;
   Put (Long_Long_Integer'Image (S));
   New_Line;
   Put_Line ("T");
   Put (Long_Long_Integer'Image
     (Long_Long_Integer (To_Duration (T1 - T0) * 1_000_000_000.0)));
   New_Line;
end B12_GCD;
