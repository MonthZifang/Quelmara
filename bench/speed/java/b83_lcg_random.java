// b83_lcg_random
class Main {
    public static void main(String[] args) {
        long seed = 12345;
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 10000000; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            acc += seed % 100;
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
