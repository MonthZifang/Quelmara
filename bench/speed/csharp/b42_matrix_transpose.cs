// b42_matrix_transpose - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b42_matrix_transpose.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 500, sz = n * n;
long[] a = new long[(int)sz], b = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i;
for (long r = 0; r < n; r++)
    for (long c = 0; c < n; c++)
        b[(int)(r * n + c)] = a[(int)(c * n + r)];
long chk = b[(int)(sz - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
