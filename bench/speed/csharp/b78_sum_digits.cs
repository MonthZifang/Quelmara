// b78_sum_digits - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b78_sum_digits.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long digit_sum(long n) {
    long s = 0;
    while (n > 0) { s += n % 10; n /= 10; }
    return s;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 0; i < 1000000; i++) acc += digit_sum(i);

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
