// b62_pred_branch - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b62_pred_branch.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 5000000; i++) {
    if ((i * 7 + 3) % 5 < 2) acc += 1; else acc -= 1;
}

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
