// b26_maxsub - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b26_maxsub.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 20000000;
ulong seed = 42;
long best = 0, cur = 0;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long v = (long)(seed % 201UL) - 100;
    cur += v;
    if (cur < 0) cur = 0;
    if (cur > best) best = cur;
}
long chk = best;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
