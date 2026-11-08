// b13_collatz —— Collatz 序列长度累加(1..30万)
class Main {
    static long clen(long n) {
        long c = 0;
        while (n != 1) { n = (n % 2 == 0) ? n / 2 : 3 * n + 1; c++; }
        return c;
    }
    public static void main(String[] args) {
        long best = 0, bn = 0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= 300000; i++) {
            long c = clen(i);
            if (c > best) { best = c; bn = i; }
        }
        long el = System.nanoTime() - t0;
        System.out.println(best * 10000000 + bn);
        System.out.println("T");
        System.out.println(el);
    }
}
