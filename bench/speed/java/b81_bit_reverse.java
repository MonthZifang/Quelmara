// b81_bit_reverse
class Main {
    static long bitrev(long x) {
        long v = x, r = 0;
        for (int i = 0; i < 32; i++) { r = (r << 1) | (v & 1); v >>= 1; }
        return r;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 1000000; j++) acc ^= bitrev(j);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
