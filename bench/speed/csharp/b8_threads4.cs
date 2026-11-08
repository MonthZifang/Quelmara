// b8_threads4 - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b8_threads4.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long work(long n) {
    long acc = 0;
    for (long i = 0; i < n; i++) acc += (i * 7) % 13;
    return acc;
}

var sw = Stopwatch.StartNew();
long r = work(40000000) + work(40000000) + work(40000000) + work(40000000);

sw.Stop();
Console.WriteLine(r);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
