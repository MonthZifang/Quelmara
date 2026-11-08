// b23_lcs —— DP：最长公共子序列 1500×1500
class Main {
    public static void main(String[] args) {
        long n = 1500;
        long[] prev = new long[(int) (n + 1)];
        long[] cur = new long[(int) (n + 1)];
        long t0 = System.nanoTime();
        for (long r = 1; r <= n; r++) {
            for (long c = 1; c <= n; c++) {
                long av = (r * 7 + 3) % 4;
                long bv = (c * 11 + 5) % 4;
                if (av == bv) cur[(int) c] = prev[(int) (c - 1)] + 1;
                else cur[(int) c] = prev[(int) c] > cur[(int) (c - 1)] ? prev[(int) c] : cur[(int) (c - 1)];
            }
            for (long c = 0; c <= n; c++) prev[(int) c] = cur[(int) c];
        }
        long el = System.nanoTime() - t0;
        System.out.println(prev[(int) n]);
        System.out.println("T");
        System.out.println(el);
    }
}
