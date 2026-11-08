// b72_sort_insert
class Main {
    public static void main(String[] args) {
        long n = 10000;
        long[] a = new long[(int) n];
        long seed = 777;
        for (long i = 0; i < n; i++) { seed = (seed * 1103515245L + 12345) % 2147483648L; a[(int) i] = seed % 100000; }
        long t0 = System.nanoTime();
        for (long x = 1; x < n; x++) {
            long key = a[(int) x], y = x - 1;
            while (y >= 0 && a[(int) y] > key) { a[(int) (y + 1)] = a[(int) y]; y--; }
            a[(int) (y + 1)] = key;
        }
        long el = System.nanoTime() - t0;
        System.out.println(a[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
