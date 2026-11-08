// b33_startup
class Main {
    static long init() {
        long s = 0;
        for (long i = 0; i < 1000; i++) s += i;
        return s;
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long a = init(), b = init(), c = init(), d = init();
        long el = System.nanoTime() - t0;
        System.out.println(a + b + c + d);
        System.out.println("T");
        System.out.println(el);
    }
}
