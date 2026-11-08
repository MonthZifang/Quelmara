// b53_thread_sim - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b53_thread_sim.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long work(long start, long end) {
    long s = 0;
    for (long i = start; i < end; i++) s += i * 2 + 1;
    return s;
}

var sw = Stopwatch.StartNew();
long n = 10000000;
long a = work(0, n / 4), b = work(n / 4, n / 2);
long c = work(n / 2, 3 * n / 4), d = work(3 * n / 4, n);
long chk = a + b + c + d;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
