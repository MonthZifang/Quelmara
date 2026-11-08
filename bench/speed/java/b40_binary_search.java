// b40_binary_search
class Main {
    static long bsearch_impl(long[] a, long n, long target) {
        long lo = 0, hi = n - 1;
        while (lo <= hi) {
            long mid = (lo + hi) / 2;
            if (a[(int) mid] == target) return mid;
            if (a[(int) mid] < target) lo = mid + 1; else hi = mid - 1;
        }
        return -1;
    }
    public static void main(String[] args) {
        long n = 1000000;
        long[] a = new long[(int) n];
        for (long i = 0; i < n; i++) a[(int) i] = i * 2;
        long found = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 1000000; j++)
            if (bsearch_impl(a, n, j * 2) >= 0) found++;
        long el = System.nanoTime() - t0;
        System.out.println(found);
        System.out.println("T");
        System.out.println(el);
    }
}
