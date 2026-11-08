// b11_nqueens - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b11_nqueens.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long solve(long[] col, long n, long r) {
    if (r == n) return 1;
    long cnt = 0;
    for (long c = 0; c < n; c++) {
        int ok = 1;
        for (long k = 0; k < r; k++) {
            long cc = col[(int)k];
            if (cc == c) ok = 0;
            long d = cc - c;
            if (d == k - r || d == r - k) ok = 0;
        }
        if (ok != 0) { col[(int)r] = c; cnt += solve(col, n, r + 1); }
    }
    return cnt;
}

var sw = Stopwatch.StartNew();
long n = 8;
long[] col = new long[8];
long total = 0;
for (long rep = 0; rep < 2000; rep++) total += solve(col, n, 0);

sw.Stop();
Console.WriteLine(total);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
