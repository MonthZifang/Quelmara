// b60_murmur - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b60_murmur.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long murmur(long h, long k) {
    long key = k;
    key = key * -862048943L;
    key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFFL);
    key = key * -862048943L;
    h ^= key;
    h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFFL);
    return h * 5 + 1;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 1000000; i++) acc = murmur(acc, i);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
