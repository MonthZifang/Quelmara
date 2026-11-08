// b40_binary_search - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b40_binary_search.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long bsearch_impl(long[] a, long n, long target) {
    long lo = 0, hi = n - 1;
    while (lo <= hi) {
        long mid = (lo + hi) / 2;
        if (a[(int)mid] == target) return mid;
        if (a[(int)mid] < target) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

var sw = Stopwatch.StartNew();
long n = 1000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 2;
long found = 0;
for (long j = 0; j < 1000000; j++)
    if (bsearch_impl(a, n, j * 2) >= 0) found++;

sw.Stop();
Console.WriteLine(found);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
