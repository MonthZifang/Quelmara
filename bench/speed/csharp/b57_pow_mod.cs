// b57_pow_mod - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b57_pow_mod.c.
using System;
using System.Diagnostics;
using System.Globalization;

static long pow_mod(long b, long exp, long mod) {
    long result = 1, bb = b % mod;
    while (exp > 0) {
        if (exp % 2 == 1) result = (result * bb) % mod;
        bb = (bb * bb) % mod; exp /= 2;
    }
    return result;
}

var sw = Stopwatch.StartNew();
long acc = 0;
for (long i = 1; i <= 1000000; i++) acc = (acc + pow_mod(i, i, 1000003)) % 1000003;

sw.Stop();
Console.WriteLine(acc);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
