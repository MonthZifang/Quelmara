// b66_integrate - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b66_integrate.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long f(long x) { return (x * x + 3 * x + 5) % 1000003; }

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 1000000; i++) acc = (acc + f(i)) % 1000003;

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
