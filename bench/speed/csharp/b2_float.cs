// b2_float - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b2_float.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 5000000;
double acc = 0.0;
for (long i = 1; i <= n; i++) acc += 1.0 / (double)i;

sw.Stop();
Console.WriteLine((acc).ToString("F6", CultureInfo.InvariantCulture));
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
