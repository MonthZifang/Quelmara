// b31_memcpy - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b31_memcpy.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 12500000;
long[] src = new long[(int)n], dst = new long[(int)n];
for (long i = 0; i < n; i++) src[(int)i] = i;
for (long j = 0; j < n; j++) dst[(int)j] = src[(int)j];
long chk = dst[(int)(n - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
