// b22_knapsack —— 0/1 背包 DP（800 件 × 800 容量）
class Main {
    public static void main(String[] args) {
        long n = 800, cap = 800;
        long[] wt = new long[(int) n];
        long[] vl = new long[(int) n];
        long seed = 999;
        for (long i = 0; i < n; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            wt[(int) i] = seed % 50 + 1;
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            vl[(int) i] = seed % 100 + 1;
        }
        long[] dp = new long[(int) (cap + 1)];
        long t0 = System.nanoTime();
        for (long it = 0; it < n; it++)
            for (long c = cap; c >= wt[(int) it]; c--) {
                long cand = dp[(int) (c - wt[(int) it])] + vl[(int) it];
                if (cand > dp[(int) c]) dp[(int) c] = cand;
            }
        long el = System.nanoTime() - t0;
        System.out.println(dp[(int) cap]);
        System.out.println("T");
        System.out.println(el);
    }
}
