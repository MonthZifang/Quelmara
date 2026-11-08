// b58_rec_sum
class Main {
    static long rec_sum(long n) {
        long s = 0;
        for (long k = 1; k <= n; k++) s += k;
        return s;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= 100; i++) acc += rec_sum(10000);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
