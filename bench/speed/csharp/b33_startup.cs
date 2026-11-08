// b33_startup - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b33_startup.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long init() {
    long s = 0;
    for (long i = 0; i < 1000; i++) s += i;
    return s;
}

var sw = Stopwatch.StartNew();
long a = init(), b = init(), c = init(), d = init();
long chk = a + b + c + d;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
