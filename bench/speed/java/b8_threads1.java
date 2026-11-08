// b8_threads1 —— 单线程 4000 万次整数运算
class Main {
    static long work(long n) {
        long acc = 0;
        for (long i = 0; i < n; i++) acc += (i * 7) % 13;
        return acc;
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long r = work(160000000);
        long el = System.nanoTime() - t0;
        System.out.println(r);
        System.out.println("T");
        System.out.println(el);
    }
}
