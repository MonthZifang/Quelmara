// b13_collatz - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b13_collatz.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long clen(long n) {
    long c = 0;
    while (n != 1) { n = (n % 2 == 0) ? n / 2 : 3 * n + 1; c++; }
    return c;
}

var sw = Stopwatch.StartNew();
long best = 0, bn = 0;
for (long i = 1; i <= 300000; i++) {
    long c = clen(i);
    if (c > best) { best = c; bn = i; }
}
long chk = best * 10000000 + bn;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
