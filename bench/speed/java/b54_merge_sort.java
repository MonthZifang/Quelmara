// b54_merge_sort
class Main {
    static long[] tmp;
    static void merge(long[] a, long lo, long mid, long hi) {
        long i = lo, j = mid, k = 0;
        while (i < mid && j < hi) tmp[(int) k++] = a[(int) i] <= a[(int) j] ? a[(int) i++] : a[(int) j++];
        while (i < mid) tmp[(int) k++] = a[(int) i++];
        while (j < hi) tmp[(int) k++] = a[(int) j++];
        for (long x = 0; x < k; x++) a[(int) (lo + x)] = tmp[(int) x];
    }
    static void msort(long[] a, long lo, long hi) {
        if (hi - lo <= 1) return;
        long mid = (lo + hi) / 2;
        msort(a, lo, mid); msort(a, mid, hi); merge(a, lo, mid, hi);
    }
    public static void main(String[] args) {
        long n = 100000;
        long[] a = new long[(int) n];
        long seed = 12345;
        for (long i = 0; i < n; i++) { seed = (seed * 1103515245L + 12345) % 2147483648L; a[(int) i] = seed % 1000000; }
        tmp = new long[(int) n];
        long t0 = System.nanoTime();
        msort(a, 0, n);
        long el = System.nanoTime() - t0;
        System.out.println(a[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
