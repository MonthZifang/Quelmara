// b45_accumulate - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b45_accumulate.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long acc = 0;
for (long n = 1; n <= 1000000; n++) {
    long s = 0;
    for (int k = 0; k < 10; k++) s = s * n + k;
    acc += s % 1000003;
}

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
