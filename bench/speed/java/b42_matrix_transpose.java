// b42_matrix_transpose
class Main {
    public static void main(String[] args) {
        long n = 500, sz = n * n;
        long[] a = new long[(int) sz];
        for (long i = 0; i < sz; i++) a[(int) i] = i;
        long[] b = new long[(int) sz];
        long t0 = System.nanoTime();
        for (long r = 0; r < n; r++)
            for (long c = 0; c < n; c++)
                b[(int) (r * n + c)] = a[(int) (c * n + r)];
        long el = System.nanoTime() - t0;
        System.out.println(b[(int) (sz - 1)]);
        System.out.println("T");
        System.out.println(el);
    }
}
