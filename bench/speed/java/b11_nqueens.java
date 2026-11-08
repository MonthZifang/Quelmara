// b11_nqueens —— N 皇后(8)：回溯 + 数组标记
class Main {
    static long solve(long[] col, long n, long r) {
        if (r == n) return 1;
        long cnt = 0;
        for (long c = 0; c < n; c++) {
            int ok = 1;
            for (long k = 0; k < r; k++) {
                long cc = col[(int) k];
                if (cc == c) ok = 0;
                long d = cc - c;
                if (d == k - r || d == r - k) ok = 0;
            }
            if (ok == 1) { col[(int) r] = c; cnt += solve(col, n, r + 1); }
        }
        return cnt;
    }
    public static void main(String[] args) {
        long n = 8;
        long[] col = new long[8];
        long total = 0;
        long t0 = System.nanoTime();
        for (long rep = 0; rep < 2000; rep++) total += solve(col, n, 0);
        long el = System.nanoTime() - t0;
        System.out.println(total);
        System.out.println("T");
        System.out.println(el);
    }
}
