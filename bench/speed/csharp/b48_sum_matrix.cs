// b48_sum_matrix - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b48_sum_matrix.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 500, sz = n * n;
long[] a = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i;
long total = 0;
for (long r = 0; r < n; r++) {
    long s = 0;
    for (long c = 0; c < n; c++) s += a[(int)(r * n + c)];
    total += s;
}

sw.Stop();
Console.WriteLine(total);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
