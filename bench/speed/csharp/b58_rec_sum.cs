// b58_rec_sum - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b58_rec_sum.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long rec_sum(long n) {
    if (n <= 0) return 0;
    return n + rec_sum(n - 1);
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 1; i <= 100; i++) acc += rec_sum(10000);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
