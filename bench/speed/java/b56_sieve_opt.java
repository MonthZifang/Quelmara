// b56_sieve_opt
class Main {
    public static void main(String[] args) {
        long n = 2000000;
        long[] flags = new long[(int) (n + 1)];
        for (long i = 0; i <= n; i++) flags[(int) i] = 1;
        flags[0] = flags[1] = 0;
        long t0 = System.nanoTime();
        for (long p = 2; p * p <= n; p++)
            if (flags[(int) p] != 0) for (long q = p * p; q <= n; q += p) flags[(int) q] = 0;
        long cnt = 0;
        for (long k = 2; k <= n; k++) if (flags[(int) k] != 0) cnt++;
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
