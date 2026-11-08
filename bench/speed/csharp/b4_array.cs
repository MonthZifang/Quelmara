// b4_array - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b4_array.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 2000000;
long[] v = new long[(int)n];
for (long i = 0; i < n; i++) v[(int)i] = i * 3 + 1;
long s = 0; for (long i = 0; i < n; i++) s += v[(int)i];
long t = 0; for (long i = 0; i < n; i += 7) t += v[(int)i];

sw.Stop();
Console.WriteLine(s);
Console.WriteLine(t);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
