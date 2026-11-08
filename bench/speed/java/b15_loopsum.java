// b15_loopsum —— 最朴素循环累加 2 亿次
class Main {
    public static void main(String[] args) {
        long n = 200000000;
        long s = 0;
        long x = 1;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) {
            x = (x * 31 + i) | 1;
            s = s + (x & 1023);
        }
        long el = System.nanoTime() - t0;
        System.out.println(s);
        System.out.println("T");
        System.out.println(el);
    }
}
