// b84_pair_swap
class Main {
    public static void main(String[] args) {
        long n = 1000000;
        long[] keys = new long[(int) n], vals = new long[(int) n];
        for (long i = 0; i < n; i++) { keys[(int) i] = i; vals[(int) i] = i * 2; }
        long t0 = System.nanoTime();
        for (long j = 0; j < n; j++) {
            long k = keys[(int) j], v = vals[(int) j];
            keys[(int) j] = v; vals[(int) j] = k;
        }
        long el = System.nanoTime() - t0;
        System.out.println(keys[0] + vals[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
