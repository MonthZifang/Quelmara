// b47_bitcount - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b47_bitcount.c.
using System;
using System.Diagnostics;
using System.Globalization;

static int popcount(long x) {
    int c = 0;
    while (x != 0) { c += (int)(x & 1); x >>= 1; }
    return c;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 10000000; i++) acc += popcount(i);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
