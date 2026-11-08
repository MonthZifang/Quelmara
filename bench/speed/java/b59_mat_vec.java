// b59_mat_vec
class Main {
    public static void main(String[] args) {
        long n = 500, sz = n * n;
        long[] mat = new long[(int) sz];
        long[] vec = new long[(int) n];
        for (long i = 0; i < sz; i++) mat[(int) i] = (i * 7 + 3) % 100;
        for (long j = 0; j < n; j++) vec[(int) j] = (j * 13 + 1) % 100;
        long total = 0;
        long t0 = System.nanoTime();
        for (long r = 0; r < n; r++) {
            long s = 0;
            for (long c = 0; c < n; c++) s += mat[(int) (r * n + c)] * vec[(int) c];
            total += s;
        }
        long el = System.nanoTime() - t0;
        System.out.println(total);
        System.out.println("T");
        System.out.println(el);
    }
}
