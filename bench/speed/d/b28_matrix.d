// b28_matrix —— 数值：矩阵乘法 300x300
import std.datetime.stopwatch;
import std.stdio;

void main() {
    enum n = 300;
    auto sz = n * n;
    auto a = new long[sz];
    auto b = new long[sz];
    auto c = new long[sz];
    ulong seed = 7;
    foreach (i; 0 .. sz) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[i] = seed % 100;
        seed = (seed * 1103515245 + 12345) % 2147483648;
        b[i] = seed % 100;
    }
    auto sw = StopWatch(AutoStart.yes);
    foreach (r; 0 .. n)
        foreach (k; 0 .. n) {
            auto av = a[r * n + k];
            foreach (j; 0 .. n)
                c[r * n + j] += av * b[k * n + j];
        }
    sw.stop();
    long chk = 0;
    foreach (i; 0 .. sz) chk = (chk + c[i]) % 1000000007;
    writeln(chk);
    writeln("T");
    writeln(sw.peek.total!"nsecs");
}
