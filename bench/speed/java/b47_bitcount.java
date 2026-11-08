// b47_bitcount
class Main {
    static int popcount(long x) {
        int c = 0;
        while (x != 0) { c += (int)(x & 1); x >>= 1; }
        return c;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 10000000; i++) acc += popcount(i);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
