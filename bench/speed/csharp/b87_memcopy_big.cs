// b87_memcopy_big - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b87_memcopy_big.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 12500000;
long[] src = new long[(int)n], dst = new long[(int)n];
for (long i = 0; i < n; i++) src[(int)i] = (long)i * 7 + 1;
for (long i = 0; i < n; i++) dst[(int)i] = src[(int)i];
long chk = dst[0] + dst[(int)(n / 2)] + dst[(int)(n - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
