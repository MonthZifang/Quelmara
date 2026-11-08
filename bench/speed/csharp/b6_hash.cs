// b6_hash - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b6_hash.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long cap = 1048576, mask = cap - 1, n = 300000;
long[] kt = new long[(int)cap], vt = new long[(int)cap];
for (long i = 1; i <= n; i++) {
    long k = i * 3 + 1;
    long h = (k * 2654435761L) & mask;
    while (kt[(int)h] != 0) h = (h + 1) & mask;
    kt[(int)h] = k; vt[(int)h] = k * 2;
}
long s = 0;
for (long i = 1; i <= n; i++) {
    long k = i * 3 + 1;
    long h = (k * 2654435761L) & mask;
    while (kt[(int)h] != k) h = (h + 1) & mask;
    s += vt[(int)h];
}

sw.Stop();
Console.WriteLine(s);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
