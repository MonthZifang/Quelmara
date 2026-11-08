// b84_pair_swap - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b84_pair_swap.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000000;
long[] keys = new long[(int)n], vals = new long[(int)n];
for (long i = 0; i < n; i++) { keys[(int)i] = i; vals[(int)i] = i * 2; }
for (long j = 0; j < n; j++) {
    long k = keys[(int)j], v = vals[(int)j];
    keys[(int)j] = v; vals[(int)j] = k;
}
long chk = keys[0] + vals[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
