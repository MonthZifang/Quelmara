// b27_sieve - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b27_sieve.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 10000000;
byte[] c = new byte[(int)n + 1];
for (long i = 0; i <= n; i++) c[(int)i] = 1;
c[0] = 0; c[1] = 0;
for (long p = 2; p * p <= n; p++)
    if (c[(int)p] != 0)
        for (long q = p * p; q <= n; q += p) c[(int)q] = 0;
long cnt = 0;
for (long i = 0; i <= n; i++) cnt += c[(int)i];

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
