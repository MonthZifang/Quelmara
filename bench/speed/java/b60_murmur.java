// b60_murmur
class Main {
    static long murmur(long h, long k) {
        long key = k;
        key *= -862048943L;
        key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFFL);
        key *= -862048943L;
        h ^= key;
        h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFFL);
        return h * 5 + 1;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 1000000; i++) acc = murmur(acc, i);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
