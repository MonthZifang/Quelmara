// b79_binary_tree
class Main {
    public static void main(String[] args) {
        long[] keys = new long[50000];
        long nn = 0;
        long seed = 42;
        long t0 = System.nanoTime();
        for (long i = 0; i < 50000; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            long key = seed % 100000;
            long pos = nn;
            for (long j = 0; j < nn; j++) if (keys[(int) j] > key) { pos = j; break; }
            for (long k = nn; k > pos; k--) keys[(int) k] = keys[(int) (k - 1)];
            keys[(int) pos] = key; nn++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(keys[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
