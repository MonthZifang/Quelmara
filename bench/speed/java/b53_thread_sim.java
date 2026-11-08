// b53_thread_sim
class Main {
    static long work(long start, long end) {
        long s = 0;
        for (long i = start; i < end; i++) s += i * 2 + 1;
        return s;
    }
    public static void main(String[] args) {
        long n = 10000000;
        long t0 = System.nanoTime();
        long a = work(0, n / 4), b = work(n / 4, n / 2);
        long c = work(n / 2, 3 * n / 4), d = work(3 * n / 4, n);
        long el = System.nanoTime() - t0;
        System.out.println(a + b + c + d);
        System.out.println("T");
        System.out.println(el);
    }
}
