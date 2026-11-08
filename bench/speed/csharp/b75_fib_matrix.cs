// b75_fib_matrix - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b75_fib_matrix.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long a0 = 1, a1 = 1, a2 = 1, a3 = 0;
long n = 1000;
while (n > 0) {
    if (n % 2 == 1) {
        long t = (a0 * a1 + a1 * a3) % 1000003, u = (a0 * a2 + a1 * a3) % 1000003;
        long v = (a2 * a1 + a3 * a3) % 1000003, w = (a2 * a1 + a3 * a3) % 1000003;
        a0 = t; a1 = u; a2 = v; a3 = w;
    }
    long b0 = (a0 * a0 + a1 * a2) % 1000003, b1 = (a0 * a1 + a1 * a3) % 1000003;
    long b2 = (a2 * a0 + a3 * a2) % 1000003, b3 = (a2 * a1 + a3 * a3) % 1000003;
    a0 = b0; a1 = b1; a2 = b2; a3 = b3;
    n /= 2;
}
long chk = a1;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
