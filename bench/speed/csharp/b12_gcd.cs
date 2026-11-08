// b12_gcd - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b12_gcd.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long gcd(long a, long b) {
    while (b != 0) { long t = b; b = a % b; a = t; }
    return a;
}

var sw = Stopwatch.StartNew();
long n = 30000000;
long s = 0;
for (long i = 1; i <= n; i++) s += gcd(i, 1000000 - i);

sw.Stop();
Console.WriteLine(s);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
