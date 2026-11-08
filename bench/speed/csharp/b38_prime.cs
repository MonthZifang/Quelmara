// b38_prime - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b38_prime.c.
using System;
using System.Diagnostics;
using System.Globalization;

static int is_prime(long n) {
    if (n < 2) return 0;
    if (n == 2) return 1;
    if (n % 2 == 0) return 0;
    for (long d = 3; d * d <= n; d += 2)
        if (n % d == 0) return 0;
    return 1;
}

var sw = Stopwatch.StartNew();
long cnt = 0;
for (long i = 0; i < 100000; i++) cnt += is_prime(i);

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
