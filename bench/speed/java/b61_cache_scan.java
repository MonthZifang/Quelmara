// b61_cache_scan
class Main {
    public static void main(String[] args) {
        long n = 1000000;
        long[] a = new long[(int) n];
        for (long i = 0; i < n; i++) a[(int) i] = i;
        long acc = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 10; j++)
            for (long k = 0; k < n; k++) acc += a[(int) k];
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
