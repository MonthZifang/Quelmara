// b50_permute - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b50_permute.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long perm(long[] arr, int k, int n, long acc) {
    if (k == n) {
        long h = 0;
        for (int i = 0; i < n; i++) h = h * 31 + arr[i];
        return acc + (h % 1000003);
    }
    long s = acc;
    for (int i = k; i < n; i++) {
        long t = arr[k]; arr[k] = arr[i]; arr[i] = t;
        s = perm(arr, k + 1, n, s);
        t = arr[k]; arr[k] = arr[i]; arr[i] = t;
    }
    return s;
}

var sw = Stopwatch.StartNew();
long[] a = new long[10];
for (int i = 0; i < 10; i++) a[i] = i + 1;
long r = perm(a, 0, 10, 0);

sw.Stop();
Console.WriteLine(r);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
