// b8_threads4 —— 同样 4000 万次总量，拆成 4 个线程（结果确定性求和）
class Main {
    static long work(long n) {
        long acc = 0;
        for (long i = 0; i < n; i++) acc += (i * 7) % 13;
        return acc;
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long a = work(40000000), b = work(40000000), c = work(40000000), d = work(40000000);
        long el = System.nanoTime() - t0;
        System.out.println(a + b + c + d);
        System.out.println("T");
        System.out.println(el);
    }
}
