// b36_call
class Main {
    static long add3(long a, long b, long c) { return a + b + c; }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 10000000; i++) acc = add3(acc, i, 1);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
