// b74_accum_poly - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b74_accum_poly.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long acc = 0;
for (long n = 1; n <= 5000000; n++) {
    long s = 0;
    for (int k = 0; k < 5; k++) s = s * n + k * 3 + 1;
    acc += s % 1000003;
}
long chk = acc % 1000003;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
