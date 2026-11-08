// b37_swap - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b37_swap.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 10000;
long[] a = new long[(int)n];
ulong seed = 42;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100000UL);
}
for (long round = 0; round < 100; round++)
    for (long j = 0; j < n - 1; j++)
        if (a[(int)j] > a[(int)(j + 1)]) { long t = a[(int)j]; a[(int)j] = a[(int)(j + 1)]; a[(int)(j + 1)] = t; }
long chk = a[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
