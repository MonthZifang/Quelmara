// b55_hash_chain
class Main {
    public static void main(String[] args) {
        long cap = 262144;
        long[] buckets = new long[(int) cap];
        long cnt = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 200000; j++) {
            long h = (j * 2654435761L) % cap;
            buckets[(int) h]++; cnt++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
