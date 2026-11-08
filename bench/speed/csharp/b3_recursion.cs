// b3_recursion - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b3_recursion.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long fib(long n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}

var sw = Stopwatch.StartNew();
long r = fib(30);

sw.Stop();
Console.WriteLine(r);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
