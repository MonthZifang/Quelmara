// b48_sum_matrix
class Main {
    public static void main(String[] args) {
        long n = 500, sz = n * n;
        long[] a = new long[(int) sz];
        for (long i = 0; i < sz; i++) a[(int) i] = i;
        long total = 0;
        long t0 = System.nanoTime();
        for (long r = 0; r < n; r++) {
            long s = 0;
            for (long c = 0; c < n; c++) s += a[(int) (r * n + c)];
            total += s;
        }
        long el = System.nanoTime() - t0;
        System.out.println(total);
        System.out.println("T");
        System.out.println(el);
    }
}
