// b32_io_write - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b32_io_write.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000000;
long[] buf = new long[(int)n];
for (long i = 0; i < n; i++) buf[(int)i] = i * 2 + 1;
long chk = buf[(int)(n - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
