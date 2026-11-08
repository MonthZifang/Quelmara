// b18_insertion —— 排序：插入排序 8 万元素
class Main {
    public static void main(String[] args) {
        long n = 80000;
        long[] a = new long[(int) n];
        long seed = 12345;
        for (long i = 0; i < n; i++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L;
            a[(int) i] = seed % 100000;
        }
        long t0 = System.nanoTime();
        for (long x = 1; x < n; x++) {
            long key = a[(int) x];
            long y = x - 1;
            while (y >= 0 && a[(int) y] > key) { a[(int) (y + 1)] = a[(int) y]; y--; }
            a[(int) (y + 1)] = key;
        }
        long el = System.nanoTime() - t0;
        long chk = 0;
        for (long i = 0; i < n; i++) chk = (chk + a[(int) i] * (i + 1)) % 1000000007;
        System.out.println(chk);
        System.out.println("T");
        System.out.println(el);
    }
}
