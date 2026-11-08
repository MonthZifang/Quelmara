// b77_rec_fib - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b77_rec_fib.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long fib(long n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

var sw = Stopwatch.StartNew();
long r = fib(25);

sw.Stop();
Console.WriteLine(r);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
