// b66_integrate
class Main {
    static long f(long x) { return (x * x + 3 * x + 5) % 1000003; }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 1000000; i++) acc = (acc + f(i)) % 1000003;
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
