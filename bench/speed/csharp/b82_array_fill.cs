// b82_array_fill - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b82_array_fill.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 5000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 2 + 1;
long chk = a[(int)(n - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
