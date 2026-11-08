// b68_bit_matrix - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b68_bit_matrix.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 256, sz = n * n;
long[] a = new long[(int)sz], b = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i % 2;
for (long r = 0; r < n; r++)
    for (long c = 0; c < n; c++)
        b[(int)(r * n + c)] = a[(int)(c * n + (n - 1 - r))];
long chk = b[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
