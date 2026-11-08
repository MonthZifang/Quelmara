// b54_merge_sort - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b54_merge_sort.c.
using System;
using System.Diagnostics;
using System.Globalization;

static void merge(long[] a, long lo, long mid, long hi, long[] tmp) {
    long i = lo, j = mid, k = 0;
    while (i < mid && j < hi) { tmp[(int)k++] = a[(int)i] <= a[(int)j] ? a[(int)i++] : a[(int)j++; }
    while (i < mid) tmp[(int)k++] = a[(int)i++];
    while (j < hi) tmp[(int)k++] = a[(int)j++];
    for (long x = 0; x < k; x++) a[(int)(lo + x)] = tmp[(int)x];
}
static void msort(long[] a, long lo, long hi, long[] tmp) {
    if (hi - lo <= 1) return;
    long mid = (lo + hi) / 2;
    msort(a, lo, mid, tmp); msort(a, mid, hi, tmp); merge(a, lo, mid, hi, tmp);
}

var sw = Stopwatch.StartNew();
long n = 100000;
long[] a = new long[(int)n], tmp = new long[(int)n];
ulong seed = 12345;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 1000000UL); }
msort(a, 0, n, tmp);
long chk = a[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
