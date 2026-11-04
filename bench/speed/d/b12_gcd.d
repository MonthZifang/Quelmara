// b12_gcd —— 整数：3000 万次辗转相除
import std.datetime.stopwatch;
import std.stdio;

long gcd(long a, long b) {
    while (b != 0) { auto t = b; b = a % b; a = t; }
    return a;
}

void main() {
    long n = 30000000;
    auto sw = StopWatch(AutoStart.yes);
    long s = 0;
    for (long i = 1; i <= n; i++) s += gcd(i, 1000000 - i);
    sw.stop();
    writeln(s);
    writeln("T");
    writeln(sw.peek.total!"nsecs");
}
