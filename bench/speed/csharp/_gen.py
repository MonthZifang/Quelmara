#!/usr/bin/env python3
# Generator for C# top-level-statement ports of the Quelmara speed benches.
# UNVERIFIED: no dotnet on the build box. Algorithms mirror bench/speed/c/<id>.c.
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER = """// {id} - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/{id}.c.
using System;
using System.Diagnostics;
using System.Globalization;
"""

FOOTER = """var sw = Stopwatch.StartNew();
{work}
sw.Stop();
{prints}Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
"""


def build(id, funcs, work, prints, is_float=False):
    ps = ""
    for p in prints:
        if is_float:
            ps += 'Console.WriteLine((%s).ToString("F6", CultureInfo.InvariantCulture));\n' % p
        else:
            ps += "Console.WriteLine(%s);\n" % p
    prog = (HEADER.replace("{id}", id) + "\n" + funcs +
            "\n" + FOOTER.format(work=work, prints=ps))
    return prog


B = []  # list of (id, funcs, work, prints, is_float)

B.append(("b1_int", "",
"""long n = 20000000, acc = 0;
for (long i = 0; i < n; i++) acc += (i * 7) % 13;
""", ["acc"]))

B.append(("b2_float", "",
"""long n = 5000000;
double acc = 0.0;
for (long i = 1; i <= n; i++) acc += 1.0 / (double)i;
""", ["acc"], True))

B.append(("b3_recursion",
"""static long fib(long n) {
    if (n < 2) return n;
    return fib(n - 1) + fib(n - 2);
}
""",
"""long r = fib(30);
""", ["r"]))

B.append(("b4_array", "",
"""long n = 2000000;
long[] v = new long[(int)n];
for (long i = 0; i < n; i++) v[(int)i] = i * 3 + 1;
long s = 0; for (long i = 0; i < n; i++) s += v[(int)i];
long t = 0; for (long i = 0; i < n; i += 7) t += v[(int)i];
""", ["s", "t"]))

B.append(("b5_string", "",
"""long n = 500000, acc = 0;
for (long i = 0; i < n; i++) {
    string buf = i.ToString();
    acc += buf.Length;
    acc += long.Parse(buf);
}
""", ["acc"]))

B.append(("b6_hash", "",
"""long cap = 1048576, mask = cap - 1, n = 300000;
long[] kt = new long[(int)cap], vt = new long[(int)cap];
for (long i = 1; i <= n; i++) {
    long k = i * 3 + 1;
    long h = (k * 2654435761L) & mask;
    while (kt[(int)h] != 0) h = (h + 1) & mask;
    kt[(int)h] = k; vt[(int)h] = k * 2;
}
long s = 0;
for (long i = 1; i <= n; i++) {
    long k = i * 3 + 1;
    long h = (k * 2654435761L) & mask;
    while (kt[(int)h] != k) h = (h + 1) & mask;
    s += vt[(int)h];
}
""", ["s"]))

B.append(("b7_sort",
"""static void qsort_i64(long[] a, long lo, long hi) {
    if (lo >= hi) return;
    long p = a[(int)hi], i = lo;
    for (long j = lo; j < hi; j++) {
        if (a[(int)j] < p) { long t = a[(int)i]; a[(int)i] = a[(int)j]; a[(int)j] = t; i++; }
    }
    long t2 = a[(int)i]; a[(int)i] = a[(int)hi]; a[(int)hi] = t2;
    qsort_i64(a, lo, i - 1);
    qsort_i64(a, i + 1, hi);
}
""",
"""long n = 200000;
long[] v = new long[(int)n];
long x = 12345;
for (long i = 0; i < n; i++) { x = (x * 1103515245L + 12345) & 2147483647L; v[(int)i] = x; }
qsort_i64(v, 0, n - 1);
long s = 0; for (long i = 0; i < n; i++) s += v[(int)i] % 1000;
""", ["v[0]", "v[(int)(n-1)]", "s"]))

B.append(("b8_threads1",
"""static long work(long n) {
    long acc = 0;
    for (long i = 0; i < n; i++) acc += (i * 7) % 13;
    return acc;
}
""",
"""long r = work(160000000);
""", ["r"]))

B.append(("b8_threads4",
"""static long work(long n) {
    long acc = 0;
    for (long i = 0; i < n; i++) acc += (i * 7) % 13;
    return acc;
}
""",
"""long r = work(40000000) + work(40000000) + work(40000000) + work(40000000);
""", ["r"]))

# b9_json handled specially below.

B.append(("b10_ackermann",
"""static long ack(long m, long n) {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}
""",
"""long r = ack(2, 8);
""", ["r"]))

B.append(("b11_nqueens",
"""static long solve(long[] col, long n, long r) {
    if (r == n) return 1;
    long cnt = 0;
    for (long c = 0; c < n; c++) {
        int ok = 1;
        for (long k = 0; k < r; k++) {
            long cc = col[(int)k];
            if (cc == c) ok = 0;
            long d = cc - c;
            if (d == k - r || d == r - k) ok = 0;
        }
        if (ok != 0) { col[(int)r] = c; cnt += solve(col, n, r + 1); }
    }
    return cnt;
}
""",
"""long n = 8;
long[] col = new long[8];
long total = 0;
for (long rep = 0; rep < 2000; rep++) total += solve(col, n, 0);
""", ["total"]))

B.append(("b12_gcd",
"""static long gcd(long a, long b) {
    while (b != 0) { long t = b; b = a % b; a = t; }
    return a;
}
""",
"""long n = 30000000;
long s = 0;
for (long i = 1; i <= n; i++) s += gcd(i, 1000000 - i);
""", ["s"]))

B.append(("b13_collatz",
"""static long clen(long n) {
    long c = 0;
    while (n != 1) { n = (n % 2 == 0) ? n / 2 : 3 * n + 1; c++; }
    return c;
}
""",
"""long best = 0, bn = 0;
for (long i = 1; i <= 300000; i++) {
    long c = clen(i);
    if (c > best) { best = c; bn = i; }
}
long chk = best * 10000000 + bn;
""", ["chk"]))

B.append(("b14_fibiter", "",
"""long n = 50000000;
long a = 0, b = 1;
for (long i = 0; i < n; i++) {
    long t = a + b;
    a = b;
    b = t % 1000000007;
}
long chk = a;
""", ["chk"]))

B.append(("b15_loopsum", "",
"""long n = 200000000;
long s = 0;
long x = 1;
for (long i = 0; i < n; i++) {
    x = (x * 31 + i) | 1;
    s = s + (x & 1023);
}
long chk = s;
""", ["chk"]))

B.append(("b16_leibniz", "",
"""long n = 20000000;
double s = 0.0;
for (long i = 0; i < n; i++) {
    double d = (double)(2 * i + 1);
    if (i % 2 == 0) s += 1.0 / d; else s -= 1.0 / d;
}
double pi = s * 4.0;
""", ["pi"], True))

B.append(("b17_bubble", "",
"""long n = 80000;
long[] a = new long[(int)n];
ulong seed = 12345;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100000UL);
}
for (long x = 0; x < n; x++)
    for (long y = 0; y < n - 1 - x; y++)
        if (a[(int)y] > a[(int)(y + 1)]) { long t = a[(int)y]; a[(int)y] = a[(int)(y + 1)]; a[(int)(y + 1)] = t; }
long chk = 0;
for (long i = 0; i < n; i++) chk = (chk + a[(int)i] * (i + 1)) % 1000000007;
""", ["chk"]))

B.append(("b18_insertion", "",
"""long n = 80000;
long[] a = new long[(int)n];
ulong seed = 12345;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100000UL);
}
for (long x = 1; x < n; x++) {
    long key = a[(int)x];
    long y = x - 1;
    while (y >= 0 && a[(int)y] > key) { a[(int)(y + 1)] = a[(int)y]; y--; }
    a[(int)(y + 1)] = key;
}
long chk = 0;
for (long i = 0; i < n; i++) chk = (chk + a[(int)i] * (i + 1)) % 1000000007;
""", ["chk"]))

B.append(("b22_knapsack", "",
"""long n = 800, cap = 800;
long[] wt = new long[(int)n], vl = new long[(int)n];
ulong seed = 999;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    wt[(int)i] = (long)(seed % 50UL) + 1;
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    vl[(int)i] = (long)(seed % 100UL) + 1;
}
long[] dp = new long[(int)cap + 1];
for (long it = 0; it < n; it++) {
    long w = wt[(int)it], v = vl[(int)it];
    for (long c = cap; c >= w; c--) {
        long cand = dp[(int)(c - w)] + v;
        if (cand > dp[(int)c]) dp[(int)c] = cand;
    }
}
long chk = dp[(int)cap];
""", ["chk"]))

B.append(("b23_lcs", "",
"""long n = 1500;
long[] prev = new long[(int)n + 1], cur = new long[(int)n + 1];
for (long r = 1; r <= n; r++) {
    for (long c = 1; c <= n; c++) {
        long av = (r * 7 + 3) % 4;
        long bv = (c * 11 + 5) % 4;
        if (av == bv) cur[(int)c] = prev[(int)(c - 1)] + 1;
        else cur[(int)c] = prev[(int)c] > cur[(int)(c - 1)] ? prev[(int)c] : cur[(int)(c - 1)];
    }
    for (long c = 0; c <= n; c++) prev[(int)c] = cur[(int)c];
}
long chk = prev[(int)n];
""", ["chk"]))

B.append(("b26_maxsub", "",
"""long n = 20000000;
ulong seed = 42;
long best = 0, cur = 0;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long v = (long)(seed % 201UL) - 100;
    cur += v;
    if (cur < 0) cur = 0;
    if (cur > best) best = cur;
}
long chk = best;
""", ["chk"]))

B.append(("b27_sieve", "",
"""long n = 10000000;
byte[] c = new byte[(int)n + 1];
for (long i = 0; i <= n; i++) c[(int)i] = 1;
c[0] = 0; c[1] = 0;
for (long p = 2; p * p <= n; p++)
    if (c[(int)p] != 0)
        for (long q = p * p; q <= n; q += p) c[(int)q] = 0;
long cnt = 0;
for (long i = 0; i <= n; i++) cnt += c[(int)i];
""", ["cnt"]))

B.append(("b28_matrix", "",
"""long n = 300;
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
""", ["chk"]))

B.append(("b31_memcpy", "",
"""long n = 12500000;
long[] src = new long[(int)n], dst = new long[(int)n];
for (long i = 0; i < n; i++) src[(int)i] = i;
for (long j = 0; j < n; j++) dst[(int)j] = src[(int)j];
long chk = dst[(int)(n - 1)];
""", ["chk"]))

B.append(("b32_io_write", "",
"""long n = 1000000;
long[] buf = new long[(int)n];
for (long i = 0; i < n; i++) buf[(int)i] = i * 2 + 1;
long chk = buf[(int)(n - 1)];
""", ["chk"]))

B.append(("b33_startup",
"""static long init() {
    long s = 0;
    for (long i = 0; i < 1000; i++) s += i;
    return s;
}
""",
"""long a = init(), b = init(), c = init(), d = init();
long chk = a + b + c + d;
""", ["chk"]))

B.append(("b34_bitops", "",
"""long acc = 0;
for (long i = 0; i < 20000000; i++)
    acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5));
""", ["acc"]))

B.append(("b35_branch", "",
"""long acc = 0;
for (long i = 0; i < 20000000; i++) {
    if ((i & 3) == 0) acc += 1; else acc -= 1;
}
""", ["acc"]))

B.append(("b36_call",
"""static long add3(long a, long b, long c) { return a + b + c; }
""",
"""long acc = 0;
for (long i = 0; i < 10000000; i++) acc = add3(acc, i, 1);
""", ["acc"]))

B.append(("b37_swap", "",
"""long n = 10000;
long[] a = new long[(int)n];
ulong seed = 42;
for (long i = 0; i < n; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    a[(int)i] = (long)(seed % 100000UL);
}
for (long round = 0; round < 100; round++)
    for (long j = 0; j < n - 1; j++)
        if (a[(int)j] > a[(int)(j + 1)]) { long t = a[(int)j]; a[(int)j] = a[(int)(j + 1)]; a[(int)(j + 1)] = t; }
long chk = a[0];
""", ["chk"]))

B.append(("b38_prime",
"""static int is_prime(long n) {
    if (n < 2) return 0;
    if (n == 2) return 1;
    if (n % 2 == 0) return 0;
    for (long d = 3; d * d <= n; d += 2)
        if (n % d == 0) return 0;
    return 1;
}
""",
"""long cnt = 0;
for (long i = 0; i < 100000; i++) cnt += is_prime(i);
""", ["cnt"]))

B.append(("b39_hash_open", "",
"""long cap = 1048576;
long[] keys = new long[(int)cap], vals = new long[(int)cap];
for (long j = 0; j < 500000; j++) {
    long h = (j * 2654435761L) % cap;
    keys[(int)h] = j; vals[(int)h] = j * 2;
}
long found = 0;
for (long k = 0; k < 500000; k++) {
    long h = (k * 2654435761L) % cap;
    if (keys[(int)h] == k) found++;
}
""", ["found"]))

B.append(("b40_binary_search",
"""static long bsearch_impl(long[] a, long n, long target) {
    long lo = 0, hi = n - 1;
    while (lo <= hi) {
        long mid = (lo + hi) / 2;
        if (a[(int)mid] == target) return mid;
        if (a[(int)mid] < target) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}
""",
"""long n = 1000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 2;
long found = 0;
for (long j = 0; j < 1000000; j++)
    if (bsearch_impl(a, n, j * 2) >= 0) found++;
""", ["found"]))

B.append(("b42_matrix_transpose", "",
"""long n = 500, sz = n * n;
long[] a = new long[(int)sz], b = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i;
for (long r = 0; r < n; r++)
    for (long c = 0; c < n; c++)
        b[(int)(r * n + c)] = a[(int)(c * n + r)];
long chk = b[(int)(sz - 1)];
""", ["chk"]))

B.append(("b43_gcd_lcm",
"""static long gcd(long a, long b) {
    while (b != 0) { long t = b; b = a % b; a = t; }
    return a;
}
""",
"""long acc = 0;
for (long i = 1; i <= 1000000; i++) acc += gcd(i, 1000000 - i + 1);
""", ["acc"]))

B.append(("b44_stack_sim", "",
"""long[] st = new long[1000000];
long top = 0;
for (long i = 0; i < 1000000; i++) {
    st[(int)top++] = i;
    if (i % 3 == 0 && top > 0) st[(int)(top - 1)]++;
}
long chk = st[(int)(top - 1)];
""", ["chk"]))

B.append(("b45_accumulate", "",
"""long acc = 0;
for (long n = 1; n <= 1000000; n++) {
    long s = 0;
    for (int k = 0; k < 10; k++) s = s * n + k;
    acc += s % 1000003;
}
""", ["acc"]))

B.append(("b46_strcat", "",
"""long acc = 0;
for (long i = 0; i < 100000; i++) {
    string s = string.Format("{0} {1} {2}", "hello", "world", "12345");
    acc += s.Length;
}
""", ["acc"]))

B.append(("b47_bitcount",
"""static int popcount(long x) {
    int c = 0;
    while (x != 0) { c += (int)(x & 1); x >>= 1; }
    return c;
}
""",
"""long acc = 0;
for (long i = 0; i < 10000000; i++) acc += popcount(i);
""", ["acc"]))

B.append(("b48_sum_matrix", "",
"""long n = 500, sz = n * n;
long[] a = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i;
long total = 0;
for (long r = 0; r < n; r++) {
    long s = 0;
    for (long c = 0; c < n; c++) s += a[(int)(r * n + c)];
    total += s;
}
""", ["total"]))

B.append(("b49_floyd", "",
"""long n = 100, sz = n * n;
long[] dist = new long[(int)sz];
for (long i = 0; i < sz; i++) dist[(int)i] = 999999;
for (long k = 0; k < n; k++) dist[(int)(k * n + k)] = 0;
ulong seed = 7;
for (long e = 0; e < 300; e++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long u = (long)(seed % (ulong)n);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long v = (long)(seed % (ulong)n);
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; long w = (long)(seed % 100UL) + 1;
    dist[(int)(u * n + v)] = w;
}
for (long a = 0; a < n; a++)
    for (long b = 0; b < n; b++)
        for (long c = 0; c < n; c++) {
            long d1 = dist[(int)(b * n + c)];
            long d2 = dist[(int)(b * n + a)] + dist[(int)(a * n + c)];
            if (d2 < d1) dist[(int)(b * n + c)] = d2;
        }
long chk = dist[(int)1];
""", ["chk"]))

B.append(("b50_permute",
"""static long perm(long[] arr, int k, int n, long acc) {
    if (k == n) {
        long h = 0;
        for (int i = 0; i < n; i++) h = h * 31 + arr[i];
        return acc + (h % 1000003);
    }
    long s = acc;
    for (int i = k; i < n; i++) {
        long t = arr[k]; arr[k] = arr[i]; arr[i] = t;
        s = perm(arr, k + 1, n, s);
        t = arr[k]; arr[k] = arr[i]; arr[i] = t;
    }
    return s;
}
""",
"""long[] a = new long[10];
for (int i = 0; i < 10; i++) a[i] = i + 1;
long r = perm(a, 0, 10, 0);
""", ["r"]))

B.append(("b52_io_scan", "",
"""long n = 1000000;
long[] buf = new long[(int)n];
for (long i = 0; i < n; i++) buf[(int)i] = i * 3 + 1;
long sum = 0;
for (long j = 0; j < n; j++) sum += buf[(int)j];
""", ["sum"]))

B.append(("b53_thread_sim",
"""static long work(long start, long end) {
    long s = 0;
    for (long i = start; i < end; i++) s += i * 2 + 1;
    return s;
}
""",
"""long n = 10000000;
long a = work(0, n / 4), b = work(n / 4, n / 2);
long c = work(n / 2, 3 * n / 4), d = work(3 * n / 4, n);
long chk = a + b + c + d;
""", ["chk"]))

B.append(("b54_merge_sort",
"""static void merge(long[] a, long lo, long mid, long hi, long[] tmp) {
    long i = lo, j = mid, k = 0;
    while (i < mid && j < hi) { tmp[(int)k++] = a[(int)i] <= a[(int)j] ? a[(int)i++] : a[(int)j++; }
    while (i < mid) tmp[(int)k++] = a[(int)i++];
    while (j < hi) tmp[(int)k++] = a[(int)j++];
    for (long x = 0; x < k; x++) a[(int)(lo + x)] = tmp[(int)x];
}
static void msort(long[] a, long lo, long hi, long[] tmp) {
    if (hi - lo <= 1) return;
    long mid = (lo + hi) / 2;
    msort(a, lo, mid, tmp); msort(a, mid, hi, tmp); merge(a, lo, mid, hi, tmp);
}
""",
"""long n = 100000;
long[] a = new long[(int)n], tmp = new long[(int)n];
ulong seed = 12345;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 1000000UL); }
msort(a, 0, n, tmp);
long chk = a[0];
""", ["chk"]))

B.append(("b55_hash_chain", "",
"""long cap = 262144;
long[] buckets = new long[(int)cap];
long cnt = 0;
for (long j = 0; j < 200000; j++) {
    long h = (j * 2654435761L) % cap;
    buckets[(int)h]++; cnt++;
}
""", ["cnt"]))

B.append(("b56_sieve_opt", "",
"""long n = 2000000;
long[] flags = new long[(int)n + 1];
for (long i = 0; i <= n; i++) flags[(int)i] = 1;
flags[0] = flags[1] = 0;
for (long p = 2; p * p <= n; p++)
    if (flags[(int)p] != 0) for (long q = p * p; q <= n; q += p) flags[(int)q] = 0;
long cnt = 0;
for (long k = 2; k <= n; k++) if (flags[(int)k] != 0) cnt++;
""", ["cnt"]))

B.append(("b57_pow_mod",
"""static long pow_mod(long b, long exp, long mod) {
    long result = 1, bb = b % mod;
    while (exp > 0) {
        if (exp % 2 == 1) result = (result * bb) % mod;
        bb = (bb * bb) % mod; exp /= 2;
    }
    return result;
}
""",
"""long acc = 0;
for (long i = 1; i <= 1000000; i++) acc = (acc + pow_mod(i, i, 1000003)) % 1000003;
""", ["acc"]))

B.append(("b58_rec_sum",
"""static long rec_sum(long n) {
    if (n <= 0) return 0;
    return n + rec_sum(n - 1);
}
""",
"""long acc = 0;
for (long i = 1; i <= 100; i++) acc += rec_sum(10000);
""", ["acc"]))

B.append(("b59_mat_vec", "",
"""long n = 500, sz = n * n;
long[] mat = new long[(int)sz], vec = new long[(int)n];
for (long i = 0; i < sz; i++) mat[(int)i] = (i * 7 + 3) % 100;
for (long j = 0; j < n; j++) vec[(int)j] = (j * 13 + 1) % 100;
long total = 0;
for (long r = 0; r < n; r++) {
    long s = 0;
    for (long c = 0; c < n; c++) s += mat[(int)(r * n + c)] * vec[(int)c];
    total += s;
}
""", ["total"]))

B.append(("b60_murmur",
"""static long murmur(long h, long k) {
    long key = k;
    key = key * -862048943L;
    key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFFL);
    key = key * -862048943L;
    h ^= key;
    h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFFL);
    return h * 5 + 1;
}
""",
"""long acc = 0;
for (long i = 0; i < 1000000; i++) acc = murmur(acc, i);
""", ["acc"]))

B.append(("b61_cache_scan", "",
"""long n = 1000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i;
long acc = 0;
for (long j = 0; j < 10; j++)
    for (long k = 0; k < n; k++) acc += a[(int)k];
""", ["acc"]))

B.append(("b62_pred_branch", "",
"""long acc = 0;
for (long i = 0; i < 5000000; i++) {
    if ((i * 7 + 3) % 5 < 2) acc += 1; else acc -= 1;
}
""", ["acc"]))

B.append(("b65_random_walk", "",
"""long x = 0, y = 0;
ulong seed = 12345;
for (long i = 0; i < 2000000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long d = (long)(seed % 4UL);
    if (d == 0) x++; else if (d == 1) x--; else if (d == 2) y++; else y--;
}
long chk = x * 1000000 + y;
""", ["chk"]))

B.append(("b66_integrate",
"""static long f(long x) { return (x * x + 3 * x + 5) % 1000003; }
""",
"""long acc = 0;
for (long i = 0; i < 1000000; i++) acc = (acc + f(i)) % 1000003;
""", ["acc"]))

B.append(("b67_bubble_opt", "",
"""long n = 5000;
long[] a = new long[(int)n];
ulong seed = 99;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 100000UL); }
int swapped = 1;
while (swapped != 0) {
    swapped = 0;
    for (long j = 0; j < n - 1; j++)
        if (a[(int)j] > a[(int)(j + 1)]) { long t = a[(int)j]; a[(int)j] = a[(int)(j + 1)]; a[(int)(j + 1)] = t; swapped = 1; }
}
long chk = a[0];
""", ["chk"]))

B.append(("b68_bit_matrix", "",
"""long n = 256, sz = n * n;
long[] a = new long[(int)sz], b = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = i % 2;
for (long r = 0; r < n; r++)
    for (long c = 0; c < n; c++)
        b[(int)(r * n + c)] = a[(int)(c * n + (n - 1 - r))];
long chk = b[0];
""", ["chk"]))

B.append(("b69_hash_fib",
"""static long fib_hash(long key, long cap) {
    return ((key * 2654435761L) % cap + cap) % cap;
}
""",
"""long cap = 524288;
long[] tab = new long[(int)cap];
long cnt = 0;
for (long j = 0; j < 500000; j++) {
    long h = fib_hash(j, cap);
    tab[(int)h]++; cnt++;
}
""", ["cnt"]))

B.append(("b70_lin_search", "",
"""long n = 1000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 3 + 7;
long found = 0;
for (long j = 0; j < 1000000; j++) {
    long target = (j * 37 + 11) % 3000;
    for (long k = 0; k < n; k++) if (a[(int)k] == target) found++;
}
""", ["found"]))

B.append(("b71_sum_squares", "",
"""long acc = 0;
for (long i = 1; i <= 1000000; i++) acc += i * i;
long chk = acc % 1000003;
""", ["chk"]))

B.append(("b72_sort_insert", "",
"""long n = 10000;
long[] a = new long[(int)n];
ulong seed = 777;
for (long i = 0; i < n; i++) { seed = (seed * 1103515245UL + 12345UL) % 2147483648UL; a[(int)i] = (long)(seed % 100000UL); }
for (long x = 1; x < n; x++) {
    long key = a[(int)x], y = x - 1;
    while (y >= 0 && a[(int)y] > key) { a[(int)(y + 1)] = a[(int)y]; y--; }
    a[(int)(y + 1)] = key;
}
long chk = a[0];
""", ["chk"]))

B.append(("b73_graph_bfs", "",
"""long n = 1000;
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
""", ["cnt"]))

B.append(("b74_accum_poly", "",
"""long acc = 0;
for (long n = 1; n <= 5000000; n++) {
    long s = 0;
    for (int k = 0; k < 5; k++) s = s * n + k * 3 + 1;
    acc += s % 1000003;
}
long chk = acc % 1000003;
""", ["chk"]))

B.append(("b75_fib_matrix", "",
"""long a0 = 1, a1 = 1, a2 = 1, a3 = 0;
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
""", ["chk"]))

B.append(("b76_io_line", "",
"""long n = 1000000;
long[] lines = new long[(int)n];
for (long i = 0; i < n; i++) lines[(int)i] = i * 7 + 3;
long sum = 0;
for (long j = 0; j < n; j++) sum += lines[(int)j] % 100;
""", ["sum"]))

B.append(("b77_rec_fib",
"""static long fib(long n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}
""",
"""long r = fib(25);
""", ["r"]))

B.append(("b78_sum_digits",
"""static long digit_sum(long n) {
    long s = 0;
    while (n > 0) { s += n % 10; n /= 10; }
    return s;
}
""",
"""long acc = 0;
for (long i = 0; i < 1000000; i++) acc += digit_sum(i);
""", ["acc"]))

B.append(("b79_binary_tree", "",
"""long[] keys = new long[50000];
long n = 0;
ulong seed = 42;
for (long i = 0; i < 50000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    long key = (long)(seed % 100000UL);
    long pos = n;
    for (long j = 0; j < n; j++) if (keys[(int)j] > key) { pos = j; break; }
    for (long k = n; k > pos; k--) keys[(int)k] = keys[(int)(k - 1)];
    keys[(int)pos] = key; n++;
}
long chk = keys[0];
""", ["chk"]))

B.append(("b81_bit_reverse",
"""static long bitrev(long x) {
    long v = x, r = 0;
    for (int i = 0; i < 32; i++) { r = (r << 1) | (v & 1); v >>= 1; }
    return r;
}
""",
"""long acc = 0;
for (long j = 0; j < 1000000; j++) acc ^= bitrev(j);
""", ["acc"]))

B.append(("b82_array_fill", "",
"""long n = 5000000;
long[] a = new long[(int)n];
for (long i = 0; i < n; i++) a[(int)i] = i * 2 + 1;
long chk = a[(int)(n - 1)];
""", ["chk"]))

B.append(("b83_lcg_random", "",
"""ulong seed = 12345;
long acc = 0;
for (long i = 0; i < 10000000; i++) {
    seed = (seed * 1103515245UL + 12345UL) % 2147483648UL;
    acc += (long)(seed % 100UL);
}
""", ["acc"]))

B.append(("b84_pair_swap", "",
"""long n = 1000000;
long[] keys = new long[(int)n], vals = new long[(int)n];
for (long i = 0; i < n; i++) { keys[(int)i] = i; vals[(int)i] = i * 2; }
for (long j = 0; j < n; j++) {
    long k = keys[(int)j], v = vals[(int)j];
    keys[(int)j] = v; vals[(int)j] = k;
}
long chk = keys[0] + vals[0];
""", ["chk"]))

B.append(("b85_count_ones",
"""static int popcount(long x) {
    int c = 0;
    while (x != 0) { c += (int)(x & 1); x >>= 1; }
    return c;
}
""",
"""long acc = 0;
for (long i = 0; i < 5000000; i++) acc += popcount(i);
""", ["acc"]))

B.append(("b86_matrix_diag", "",
"""long n = 1000, sz = n * n;
long[] a = new long[(int)sz];
for (long i = 0; i < sz; i++) a[(int)i] = (i * 7 + 3) % 100;
long sum = 0;
for (long r = 0; r < n; r++) sum += a[(int)(r * n + r)];
""", ["sum"]))

B.append(("b87_memcopy_big", "",
"""long n = 12500000;
long[] src = new long[(int)n], dst = new long[(int)n];
for (long i = 0; i < n; i++) src[(int)i] = (long)i * 7 + 1;
for (long i = 0; i < n; i++) dst[(int)i] = src[(int)i];
long chk = dst[0] + dst[(int)(n / 2)] + dst[(int)(n - 1)];
""", ["chk"]))


# ---- b9_json (special: DOC string extracted from the C source) ----
def make_b9():
    csrc = open(os.path.join(HERE, "..", "c", "b9_json.c")).read()
    m = re.search(r'DOC = "(.*?)";', csrc, re.S)
    c_lit = m.group(1)
    # unescape C escapes
    doc = (c_lit.replace('\\"', '"').replace("\\\\", "\\"))
    # produce a C# escaped string literal
    cs_doc = '"' + doc.replace("\\", "\\\\").replace('"', '\\"') + '"'
    funcs = (
        "string DOC = " + cs_doc + ";\n"
        "long dn = DOC.Length;\n"
        "long jws(string s, long p0) {\n"
        "    long p = p0;\n"
        "    while (p < dn) {\n"
        "        char c = s[(int)p];\n"
        "        if (c == ' ' || c == '\\t' || c == '\\n' || c == '\\r') p++; else break;\n"
        "    }\n"
        "    return p;\n"
        "}\n"
        "long jstr(string s, long p0) {\n"
        "    long p = p0 + 1;\n"
        "    while (p < dn) { if (s[(int)p] == '\"') break; p++; }\n"
        "    return p + 1;\n"
        "}\n"
        "long jnum(string s, long p0, out long st) {\n"
        "    long p = p0, v = 0; int neg = 0;\n"
        "    if (p < dn && s[(int)p] == '-') { neg = 1; p++; }\n"
        "    while (p < dn) {\n"
        "        char c = s[(int)p];\n"
        "        if (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); p++; } else break;\n"
        "    }\n"
        "    if (neg != 0) v = -v;\n"
        "    st = p; return v;\n"
        "}\n"
        "long jval(string s, long p0, out long st) {\n"
        "    long p = jws(s, p0);\n"
        "    if (p >= dn) { st = p; return 0; }\n"
        "    char c = s[(int)p];\n"
        "    if (c == '{') {\n"
        "        long q = jws(s, p + 1); long acc = 0;\n"
        "        if (q < dn && s[(int)q] == '}') { st = q + 1; return 0; }\n"
        "        for (;;) {\n"
        "            q = jws(s, q);\n"
        "            q = jstr(s, q);\n"
        "            q = jws(s, q);\n"
        "            q++;\n"
        "            acc += jval(s, q, out st);\n"
        "            q = jws(s, st);\n"
        "            if (q < dn && s[(int)q] == ',') q++; else break;\n"
        "        }\n"
        "        st = q + 1; return acc;\n"
        "    }\n"
        "    if (c == '[') {\n"
        "        long q = jws(s, p + 1); long acc = 0;\n"
        "        if (q < dn && s[(int)q] == ']') { st = q + 1; return 0; }\n"
        "        for (;;) {\n"
        "            acc += jval(s, q, out st);\n"
        "            q = jws(s, st);\n"
        "            if (q < dn && s[(int)q] == ',') q++; else break;\n"
        "        }\n"
        "        st = q + 1; return acc;\n"
        "    }\n"
        "    if (c == '\"') { st = jstr(s, p); return 0; }\n"
        "    if (c == '-' || (c >= '0' && c <= '9')) return jnum(s, p, out st);\n"
        "    long q2 = p;\n"
        "    while (q2 < dn) { char d = s[(int)q2]; if (d >= 'a' && d <= 'z') q2++; else break; }\n"
        "    st = q2; return 0;\n"
        "}\n"
    )
    work = (
        "long st = 0, total = 0;\n"
        "for (long r = 0; r < 2000; r++) { st = 0; total += jval(DOC, 0, out st); }\n"
        "long chk = total;\n"
    )
    return build("b9_json", funcs, work, ["chk"])


# Write all files.
written = 0
for item in B:
    id_, funcs, work, prints = item[0], item[1], item[2], item[3]
    isf = item[4] if len(item) > 4 else False
    content = build(id_, funcs, work, prints, isf)
    with open(os.path.join(HERE, id_ + ".cs"), "w") as f:
        f.write(content)
    written += 1

# b9
content = make_b9()
with open(os.path.join(HERE, "b9_json.cs"), "w") as f:
    f.write(content)
written += 1

print("written", written)
