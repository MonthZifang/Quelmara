// b49_floyd - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b49_floyd.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 100, sz = n * n;
long[] dist = new long[(int)sz];
for (long i = 0; i < sz; i++) dist[(int)i] = 999999;
for (long k = 0; k < n; k++) dist[(int)(k * n + k)] = 0;
ulong seed = 7;
for (long e = 0; e < 300; e++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long u = (long)(seed % (ulong)n);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long v = (long)(seed % (ulong)n);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long w = (long)(seed % 100UL) + 1;
    dist[(int)(u * n + v)] = w;
}
for (long a = 0; a < n; a++)
    for (long b = 0; b < n; b++)
        for (long c = 0; c < n; c++) {
            long d1 = dist[(int)(b * n + c)];
            long d2 = dist[(int)(b * n + a)] + dist[(int)(a * n + c)];
            if (d2 < d1) dist[(int)(b * n + c)] = d2;
        }
long chk = dist[(int)1];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
