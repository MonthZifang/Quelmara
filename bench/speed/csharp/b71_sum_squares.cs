// b71_sum_squares - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b71_sum_squares.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 1; i <= 1000000; i++) acc += i * i;
long chk = acc % 1000003;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
