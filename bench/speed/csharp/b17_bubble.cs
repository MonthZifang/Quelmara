// b17_bubble - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b17_bubble.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 80000;
long[] a = new long[(int)n];
ulong seed = 12345;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100000UL);
}
for (long x = 0; x < n; x++)
    for (long y = 0; y < n - 1 - x; y++)
        if (a[(int)y] > a[(int)(y + 1)]) { long t = a[(int)y]; a[(int)y] = a[(int)(y + 1)]; a[(int)(y + 1)] = t; }
long chk = 0;
for (long i = 0; i < n; i++) chk = (chk + a[(int)i] * (i + 1)) % 1000000007;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
