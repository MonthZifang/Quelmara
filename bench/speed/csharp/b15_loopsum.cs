// b15_loopsum - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b15_loopsum.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 200000000;
long s = 0;
long x = 1;
for (long i = 0; i < n; i++) {
    x = (x * 31 + i) | 1;
    s = s + (x & 1023);
}
long chk = s;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
