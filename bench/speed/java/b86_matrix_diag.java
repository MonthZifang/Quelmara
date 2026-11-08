// b86_matrix_diag
class Main {
    public static void main(String[] args) {
        long n = 1000, sz = n * n;
        long[] a = new long[(int) sz];
        for (long i = 0; i < sz; i++) a[(int) i] = (i * 7 + 3) % 100;
        long sum = 0;
        long t0 = System.nanoTime();
        for (long r = 0; r < n; r++) sum += a[(int) (r * n + r)];
        long el = System.nanoTime() - t0;
        System.out.println(sum);
        System.out.println("T");
        System.out.println(el);
    }
}
