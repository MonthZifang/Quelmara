// b67_bubble_opt - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b67_bubble_opt.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 5000;
long[] a = new long[(int)n];
ulong seed = 99;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 100000UL); }
int swapped = 1;
while (swapped != 0) {
    swapped = 0;
    for (long j = 0; j < n - 1; j++)
        if (a[(int)j] > a[(int)(j + 1)]) { long t = a[(int)j]; a[(int)j] = a[(int)(j + 1)]; a[(int)(j + 1)] = t; swapped = 1; }
}
long chk = a[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
