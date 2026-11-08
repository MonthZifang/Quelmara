// b16_leibniz - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b16_leibniz.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 20000000;
double s = 0.0;
for (long i = 0; i < n; i++) {
    double d = (double)(2 * i + 1);
    if (i % 2 == 0) s += 1.0 / d; else s -= 1.0 / d;
}
double pi = s * 4.0;

sw.Stop();
Console.WriteLine((pi).ToString("F6", CultureInfo.InvariantCulture));
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
