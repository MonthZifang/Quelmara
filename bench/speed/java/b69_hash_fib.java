// b69_hash_fib
class Main {
    static long fib_hash(long key, long cap) {
        return ((key * 2654435761L) % cap + cap) % cap;
    }
    public static void main(String[] args) {
        long cap = 524288;
        long[] tab = new long[(int) cap];
        long cnt = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 500000; j++) {
            long h = fib_hash(j, cap);
            tab[(int) h]++; cnt++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
