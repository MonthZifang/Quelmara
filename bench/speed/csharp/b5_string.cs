// b5_string - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b5_string.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 500000, acc = 0;
for (long i = 0; i < n; i++) {
    string buf = i.ToString();
    acc += buf.Length;
    acc += long.Parse(buf);
}

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
