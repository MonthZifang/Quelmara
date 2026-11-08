// b81_bit_reverse - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b81_bit_reverse.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long bitrev(long x) {
    long v = x, r = 0;
    for (int i = 0; i < 32; i++) { r = (r << 1) | (v & 1); v >>= 1; }
    return r;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long j = 0; j < 1000000; j++) acc ^= bitrev(j);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
