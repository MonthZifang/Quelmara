// b28_matrix - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b28_matrix.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 300;
long[] a = new long[(int)n * (int)n];
long[] b = new long[(int)n * (int)n];
long[] c = new long[(int)n * (int)n];
ulong seed = 7;
for (long i = 0; i < n * n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100UL);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    b[(int)i] = (long)(seed % 100UL);
}
for (long r = 0; r < n; r++)
    for (long k = 0; k < n; k++) {
        long av = a[(int)(r * n + k)];
        for (long j = 0; j < n; j++)
            c[(int)(r * n + j)] += av * b[(int)(k * n + j)];
    }
long chk = 0;
for (long i = 0; i < n * n; i++) chk = (chk + c[(int)i]) % 1000000007;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
