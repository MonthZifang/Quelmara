// b65_random_walk - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b65_random_walk.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long x = 0, y = 0;
ulong seed = 12345;
for (long i = 0; i < 2000000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long d = (long)(seed % 4UL);
    if (d == 0) x++; else if (d == 1) x--; else if (d == 2) y++; else y--;
}
long chk = x * 1000000 + y;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
