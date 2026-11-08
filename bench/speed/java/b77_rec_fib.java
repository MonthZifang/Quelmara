// b77_rec_fib
class Main {
    static long fib(long n) {
        if (n <= 1) return n;
        return fib(n - 1) + fib(n - 2);
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long r = fib(25);
        long el = System.nanoTime() - t0;
        System.out.println(r);
        System.out.println("T");
        System.out.println(el);
    }
}
