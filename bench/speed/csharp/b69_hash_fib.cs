// b69_hash_fib - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b69_hash_fib.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long fib_hash(long key, long cap) {
    return ((key * 2654435761L) % cap + cap) % cap;
}

var sw = Stopwatch.StartNew();
long cap = 524288;
long[] tab = new long[(int)cap];
long cnt = 0;
for (long j = 0; j < 500000; j++) {
    long h = fib_hash(j, cap);
    tab[(int)h]++; cnt++;
}

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
