// b2_float —— 浮点运算：调和级数前 5M 项
class Main {
    public static void main(String[] args) {
        long n = 5000000;
        double acc = 0.0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= n; i++) acc += 1.0 / (double) i;
        long el = System.nanoTime() - t0;
        System.out.printf("%.6f\n", acc);
        System.out.println("T");
        System.out.println(el);
    }
}
