// b73_graph_bfs - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b73_graph_bfs.c.
using System;
using System.Diagnostics;
using System.Globalization;


var sw = Stopwatch.StartNew();
long n = 1000;
long[] adj = new long[(int)n * (int)n];
ulong seed = 55;
for (long e = 0; e < 5000; e++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long u = (long)(seed % (ulong)n);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long v = (long)(seed % (ulong)n);
    adj[(int)(u * n + v)] = 1;
}
long[] visited = new long[(int)n];
long[] queue = new long[(int)n];
long front = 0, back = 0;
queue[(int)back++] = 0; visited[0] = 1;
long cnt = 0;
while (front < back) {
    long u = queue[(int)front++];
    cnt++;
    for (long v = 0; v < n; v++)
        if (adj[(int)(u * n + v)] != 0 && visited[(int)v] == 0) { visited[(int)v] = 1; queue[(int)back++] = v; }
}

sw.Stop();
Console.WriteLine(cnt);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
