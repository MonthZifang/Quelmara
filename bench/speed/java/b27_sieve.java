// b27_sieve —— 埃氏筛 5000 万
class Main {
    public static void main(String[] args) {
        long n = 10000000;
        byte[] c = new byte[(int) (n + 1)];
        for (long i = 0; i <= n; i++) c[(int) i] = 1;
        c[0] = 0; c[1] = 0;
        long t0 = System.nanoTime();
        for (long p = 2; p * p <= n; p++)
            if (c[(int) p] != 0)
                for (long q = p * p; q <= n; q += p) c[(int) q] = 0;
        long cnt = 0;
        for (long i = 0; i <= n; i++) cnt += c[(int) i];
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
