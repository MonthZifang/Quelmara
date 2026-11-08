// b28_matrix —— 矩阵乘法 300×300
class Main {
    public static void main(String[] args) {
        long n = 300;
        int sz = (int) (n * n);
        long[] a = new long[sz];
        long[] b = new long[sz];
        long[] c = new long[sz];
        long seed = 7;
        for (int i = 0; i < sz; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            a[i] = seed % 100;
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            b[i] = seed % 100;
        }
        long t0 = System.nanoTime();
        for (int r = 0; r < n; r++)
            for (int k = 0; k < n; k++) {
                long av = a[r * (int) n + k];
                for (int j = 0; j < n; j++)
                    c[r * (int) n + j] += av * b[k * (int) n + j];
            }
        long el = System.nanoTime() - t0;
        long chk = 0;
        for (int i = 0; i < sz; i++) chk = (chk + c[i]) % 1000000007;
        System.out.println(chk);
        System.out.println("T");
        System.out.println(el);
    }
}
