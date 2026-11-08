// b39_hash_open - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b39_hash_open.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long cap = 1048576;
long[] keys = new long[(int)cap], vals = new long[(int)cap];
for (long j = 0; j < 500000; j++) {
    long h = (j * 2654435761L) % cap;
    keys[(int)h] = j; vals[(int)h] = j * 2;
}
long found = 0;
for (long k = 0; k < 500000; k++) {
    long h = (k * 2654435761L) % cap;
    if (keys[(int)h] == k) found++;
}

sw.Stop();
Console.WriteLine(found);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
