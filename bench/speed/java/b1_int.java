// b1_int —— 整数运算热循环，20M 次
class Main {
    public static void main(String[] args) {
        long n = 20000000, acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) acc += (i * 7) % 13;
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
