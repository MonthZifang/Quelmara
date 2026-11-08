// b22_knapsack - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b22_knapsack.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 800, cap = 800;
long[] wt = new long[(int)n], vl = new long[(int)n];
ulong seed = 999;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    wt[(int)i] = (long)(seed % 50UL) + 1;
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    vl[(int)i] = (long)(seed % 100UL) + 1;
}
long[] dp = new long[(int)cap + 1];
for (long it = 0; it < n; it++) {
    long w = wt[(int)it], v = vl[(int)it];
    for (long c = cap; c >= w; c--) {
        long cand = dp[(int)(c - w)] + v;
        if (cand > dp[(int)c]) dp[(int)c] = cand;
    }
}
long chk = dp[(int)cap];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
