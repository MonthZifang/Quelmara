// b59_mat_vec - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b59_mat_vec.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 500, sz = n * n;
long[] mat = new long[(int)sz], vec = new long[(int)n];
for (long i = 0; i < sz; i++) mat[(int)i] = (i * 7 + 3) % 100;
for (long j = 0; j < n; j++) vec[(int)j] = (j * 13 + 1) % 100;
long total = 0;
for (long r = 0; r < n; r++) {
    long s = 0;
    for (long c = 0; c < n; c++) s += mat[(int)(r * n + c)] * vec[(int)c];
    total += s;
}

sw.Stop();
Console.WriteLine(total);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
