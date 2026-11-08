// b34_bitops
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 20000000; i++)
            acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5));
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
