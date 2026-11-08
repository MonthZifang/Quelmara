// b14_fibiter - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b14_fibiter.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 50000000;
long a = 0, b = 1;
for (long i = 0; i < n; i++) {
    long t = a + b;
    a = b;
    b = t % 1000000007;
}
long chk = a;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
