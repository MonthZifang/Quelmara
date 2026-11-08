// b44_stack_sim - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b44_stack_sim.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long[] st = new long[1000000];
long top = 0;
for (long i = 0; i < 1000000; i++) {
    st[(int)top++] = i;
    if (i % 3 == 0 && top > 0) st[(int)(top - 1)]++;
}
long chk = st[(int)(top - 1)];

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
