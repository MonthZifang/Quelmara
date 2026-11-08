// b87_memcopy_big —— 内存：mem_copy 大块 100MB
class Main {
    public static void main(String[] args) {
        long n = 12500000;
        long[] src = new long[(int) n];
        long[] dst = new long[(int) n];
        for (long i = 0; i < n; i++) src[(int) i] = (long) i * 7 + 1;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) dst[(int) i] = src[(int) i];
        long el = System.nanoTime() - t0;
        long chk = dst[0] + dst[(int) (6250000)] + dst[(int) (n - 1)];
        System.out.println(chk);
        System.out.println("T");
        System.out.println(el);
    }
}
