// b56_sieve_opt - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b56_sieve_opt.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 2000000;
long[] flags = new long[(int)n + 1];
for (long i = 0; i <= n; i++) flags[(int)i] = 1;
flags[0] = flags[1] = 0;
for (long p = 2; p * p <= n; p++)
    if (flags[(int)p] != 0) for (long q = p * p; q <= n; q += p) flags[(int)q] = 0;
long cnt = 0;
for (long k = 2; k <= n; k++) if (flags[(int)k] != 0) cnt++;

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
