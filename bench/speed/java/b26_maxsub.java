// b26_maxsub —— Kadane 最大子数组 2000 万
class Main {
    public static void main(String[] args) {
        long n = 20000000;
        long seed = 42;
        long best = 0, cur = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            long v = (long) (seed % 201) - 100;
            cur += v;
            if (cur < 0) cur = 0;
            if (cur > best) best = cur;
        }
        long el = System.nanoTime() - t0;
        System.out.println(best);
        System.out.println("T");
        System.out.println(el);
    }
}
