// b39_hash_open
class Main {
    public static void main(String[] args) {
        long cap = 1048576;
        long[] keys = new long[(int) cap];
        long[] vals = new long[(int) cap];
        long t0 = System.nanoTime();
        for (long j = 0; j < 500000; j++) {
            long h = (j * 2654435761L) % cap;
            keys[(int) h] = j; vals[(int) h] = j * 2;
        }
        long found = 0;
        for (long k = 0; k < 500000; k++) {
            long h = (k * 2654435761L) % cap;
            if (keys[(int) h] == k) found++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(found);
        System.out.println("T");
        System.out.println(el);
    }
}
