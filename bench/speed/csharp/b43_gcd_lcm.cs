// b43_gcd_lcm - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b43_gcd_lcm.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long gcd(long a, long b) {
    while (b != 0) { long t = b; b = a % b; a = t; }
    return a;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 1; i <= 1000000; i++) acc += gcd(i, 1000000 - i + 1);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
