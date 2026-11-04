// b28_matrix —— 数值：矩阵乘法 300x300
public class B28Matrix {
    public static void main(String[] args) {
        int n = 300;
        int sz = n * n;
        long[] a = new long[sz];
        long[] b = new long[sz];
        long[] c = new long[sz];
        long seed = 7;
        for (int i = 0; i < sz; i++) {
            seed = (seed * 1103515245 + 12345) % 2147483648L;
            a[i] = seed % 100;
            seed = (seed * 1103515245 + 12345) % 2147483648L;
            b[i] = seed % 100;
        }
        long t0 = System.nanoTime();
        for (int r = 0; r < n; r++)
            for (int k = 0; k < n; k++) {
                long av = a[r * n + k];
                for (int j = 0; j < n; j++)
                    c[r * n + j] += av * b[k * n + j];
            }
        long t1 = System.nanoTime();
        long chk = 0;
        for (int i = 0; i < sz; i++) chk = (chk + c[i]) % 1000000007;
        System.out.println(chk);
        System.out.println("T");
        System.out.println(t1 - t0);
    }
}
