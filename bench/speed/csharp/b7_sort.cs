// b7_sort - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b7_sort.c.
using System;
using System.Diagnostics;
using System.Globalization;

static void qsort_i64(long[] a, long lo, long hi) {
    if (lo >= hi) return;
    long p = a[(int)hi], i = lo;
    for (long j = lo; j < hi; j++) {
        if (a[(int)j] < p) { long t = a[(int)i]; a[(int)i] = a[(int)j]; a[(int)j] = t; i++; }
    }
    long t2 = a[(int)i]; a[(int)i] = a[(int)hi]; a[(int)hi] = t2;
    qsort_i64(a, lo, i - 1);
    qsort_i64(a, i + 1, hi);
}

var sw = Stopwatch.StartNew();
long n = 200000;
long[] v = new long[(int)n];
long x = 12345;
for (long i = 0; i < n; i++) { x = (x * 1103515245L + 12345) & 2147483647L; v[(int)i] = x; }
qsort_i64(v, 0, n - 1);
long s = 0; for (long i = 0; i < n; i++) s += v[(int)i] % 1000;

sw.Stop();
Console.WriteLine(v[0]);
Console.WriteLine(v[(int)(n-1)]);
Console.WriteLine(s);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
