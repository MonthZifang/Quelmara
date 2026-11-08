// b52_io_scan - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b52_io_scan.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000000;
long[] buf = new long[(int)n];
for (long i = 0; i < n; i++) buf[(int)i] = i * 3 + 1;
long sum = 0;
for (long j = 0; j < n; j++) sum += buf[(int)j];

sw.Stop();
Console.WriteLine(sum);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
