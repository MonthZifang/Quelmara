// b86_matrix_diag - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b86_matrix_diag.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000, sz = n * n;
long[] a = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = (i * 7 + 3) % 100;
long sum = 0;
for (long r = 0; r < n; r++) sum += a[(int)(r * n + r)];

sw.Stop();
Console.WriteLine(sum);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
