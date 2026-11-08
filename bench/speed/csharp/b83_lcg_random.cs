// b83_lcg_random - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b83_lcg_random.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
ulong seed = 12345;
long acc = 0;
for (long i = 0; i < 10000000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    acc += (long)(seed % 100UL);
}

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
