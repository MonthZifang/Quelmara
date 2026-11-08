// b61_cache_scan - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b61_cache_scan.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i;
long acc = 0;
for (long j = 0; j < 10; j++)
    for (long k = 0; k < n; k++) acc += a[(int)k];

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
