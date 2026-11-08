// b6_hash —— 手写开放寻址哈希表，10 万插入 + 10 万查找
class Main {
    public static void main(String[] args) {
        long cap = 1048576, mask = cap - 1, n = 300000;
        long[] kt = new long[(int) cap];
        long[] vt = new long[(int) cap];
        for (long i = 1; i <= n; i++) {
            long k = i * 3 + 1;
            long h = (k * 2654435761L) & mask;
            while (kt[(int) h] != 0) h = (h + 1) & mask;
            kt[(int) h] = k;
            vt[(int) h] = k * 2;
        }
        long s = 0;
        for (long i = 1; i <= n; i++) {
            long k = i * 3 + 1;
            long h = (k * 2654435761L) & mask;
            while (kt[(int) h] != k) h = (h + 1) & mask;
            s += vt[(int) h];
        }
        long t0 = System.nanoTime();
        long el = System.nanoTime() - t0;
        System.out.println(s);
        System.out.println("T");
        System.out.println(el);
    }
}
