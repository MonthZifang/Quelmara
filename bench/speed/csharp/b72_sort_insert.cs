// b72_sort_insert - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b72_sort_insert.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 10000;
long[] a = new long[(int)n];
ulong seed = 777;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 100000UL); }
for (long x = 1; x < n; x++) {
    long key = a[(int)x], y = x - 1;
    while (y >= 0 && a[(int)y] > key) { a[(int)(y + 1)] = a[(int)y]; y--; }
    a[(int)(y + 1)] = key;
}
long chk = a[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
