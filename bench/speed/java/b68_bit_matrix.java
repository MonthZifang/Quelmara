// b68_bit_matrix
class Main {
    public static void main(String[] args) {
        long n = 256, sz = n * n;
        long[] a = new long[(int) sz];
        for (long i = 0; i < sz; i++) a[(int) i] = i % 2;
        long[] b = new long[(int) sz];
        long t0 = System.nanoTime();
        for (long r = 0; r < n; r++)
            for (long c = 0; c < n; c++)
                b[(int) (r * n + c)] = a[(int) (c * n + (n - 1 - r))];
        long el = System.nanoTime() - t0;
        System.out.println(b[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
