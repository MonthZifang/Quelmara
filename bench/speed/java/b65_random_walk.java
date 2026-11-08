// b65_random_walk
class Main {
    public static void main(String[] args) {
        long x = 0, y = 0;
        long seed = 12345;
        long t0 = System.nanoTime();
        for (long i = 0; i < 2000000; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            long d = seed % 4;
            if (d == 0) x++; else if (d == 1) x--; else if (d == 2) y++; else y--;
        }
        long el = System.nanoTime() - t0;
        System.out.println(x * 1000000 + y);
        System.out.println("T");
        System.out.println(el);
    }
}
