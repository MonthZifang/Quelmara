// b23_lcs - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b23_lcs.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1500;
long[] prev = new long[(int)n + 1], cur = new long[(int)n + 1];
for (long r = 1; r <= n; r++) {
    for (long c = 1; c <= n; c++) {
        long av = (r * 7 + 3) % 4;
        long bv = (c * 11 + 5) % 4;
        if (av == bv) cur[(int)c] = prev[(int)(c - 1)] + 1;
        else cur[(int)c] = prev[(int)c] > cur[(int)(c - 1)] ? prev[(int)c] : cur[(int)(c - 1)];
    }
    for (long c = 0; c <= n; c++) prev[(int)c] = cur[(int)c];
}
long chk = prev[(int)n];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
