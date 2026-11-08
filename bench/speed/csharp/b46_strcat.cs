// b46_strcat - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b46_strcat.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 100000; i++) {
    string s = string.Format("{0} {1} {2}", "hello", "world", "12345");
    acc += s.Length;
}

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
