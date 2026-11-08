// b79_binary_tree - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b79_binary_tree.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long[] keys = new long[50000];
long n = 0;
ulong seed = 42;
for (long i = 0; i < 50000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long key = (long)(seed % 100000UL);
    long pos = n;
    for (long j = 0; j < n; j++) if (keys[(int)j] > key) { pos = j; break; }
    for (long k = n; k > pos; k--) keys[(int)k] = keys[(int)(k - 1)];
    keys[(int)pos] = key; n++;
}
long chk = keys[0];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
