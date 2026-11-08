// b7_sort —— 手写快排，20 万个伪随机 int
class Main {
    static long[] v;
    static void qsort_i64(long lo, long hi) {
        if (lo >= hi) return;
        long p = v[(int) hi];
        long i = lo;
        for (long j = lo; j < hi; j++) {
            if (v[(int) j] < p) {
                long t = v[(int) i]; v[(int) i] = v[(int) j]; v[(int) j] = t;
                i++;
            }
        }
        long t2 = v[(int) i]; v[(int) i] = v[(int) hi]; v[(int) hi] = t2;
        qsort_i64(lo, i - 1);
        qsort_i64(i + 1, hi);
    }
    public static void main(String[] args) {
        long n = 200000;
        v = new long[(int) n];
        long x = 12345;
        for (long i = 0; i < n; i++) {
            x = (x * 1103515245L + 12345) & 2147483647L;
            v[(int) i] = x;
        }
        qsort_i64(0, n - 1);
        long s = 0;
        for (long i = 0; i < n; i++) s += v[(int) i] % 1000;
        long t0 = System.nanoTime();
        long el = System.nanoTime() - t0;
        System.out.println(v[0]);
        System.out.println(v[(int) (n - 1)]);
        System.out.println(s);
        System.out.println("T");
        System.out.println(el);
    }
}
