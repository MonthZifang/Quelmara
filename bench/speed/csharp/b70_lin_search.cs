// b70_lin_search - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b70_lin_search.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 3 + 7;
long found = 0;
for (long j = 0; j < 1000000; j++) {
    long target = (j * 37 + 11) % 3000;
    for (long k = 0; k < n; k++) if (a[(int)k] == target) found++;
}

sw.Stop();
Console.WriteLine(found);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
