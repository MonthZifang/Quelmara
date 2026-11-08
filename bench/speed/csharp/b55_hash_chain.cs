// b55_hash_chain - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b55_hash_chain.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long cap = 262144;
long[] buckets = new long[(int)cap];
long cnt = 0;
for (long j = 0; j < 200000; j++) {
    long h = (j * 2654435761L) % cap;
    buckets[(int)h]++; cnt++;
}

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
