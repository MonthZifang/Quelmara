// b36_call - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b36_call.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long add3(long a, long b, long c) { return a + b + c; }

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 10000000; i++) acc = add3(acc, i, 1);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
