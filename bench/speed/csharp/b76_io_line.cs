// b76_io_line - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b76_io_line.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000000;
long[] lines = new long[(int)n];
for (long i = 0; i < n; i++) lines[(int)i] = i * 7 + 3;
long sum = 0;
for (long j = 0; j < n; j++) sum += lines[(int)j] % 100;

sw.Stop();
Console.WriteLine(sum);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
