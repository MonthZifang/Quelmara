// b10_ackermann - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b10_ackermann.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long ack(long m, long n) {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}

var sw = Stopwatch.StartNew();
long r = ack(2, 8);

sw.Stop();
Console.WriteLine(r);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
