// b49_floyd
class Main {
    public static void main(String[] args) {
        long n = 100, sz = n * n;
        long[] dist = new long[(int) sz];
        for (long i = 0; i < sz; i++) dist[(int) i] = 999999;
        for (long k = 0; k < n; k++) dist[(int) (k * n + k)] = 0;
        long seed = 7;
        for (long e = 0; e < 300; e++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L; long u = seed % n;
            seed = (seed * 1103515245L + 12345) % 2147483648L; long v = seed % n;
            seed = (seed * 1103515245L + 12345) % 2147483648L; long w = seed % 100 + 1;
            dist[(int) (u * n + v)] = w;
        }
        long t0 = System.nanoTime();
        for (long a = 0; a < n; a++)
            for (long b = 0; b < n; b++)
                for (long c = 0; c < n; c++) {
                    long d1 = dist[(int) (b * n + c)];
                    long d2 = dist[(int) (b * n + a)] + dist[(int) (a * n + c)];
                    if (d2 < d1) dist[(int) (b * n + c)] = d2;
                }
        long el = System.nanoTime() - t0;
        System.out.println(dist[(int) 1]);
        System.out.println("T");
        System.out.println(el);
    }
}
