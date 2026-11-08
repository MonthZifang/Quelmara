// b16_leibniz —— 浮点：Leibniz 级数 π，2000 万项
class Main {
    public static void main(String[] args) {
        long n = 20000000;
        double s = 0.0;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) {
            double d = (double) (2 * i + 1);
            if (i % 2 == 0) s += 1.0 / d; else s -= 1.0 / d;
        }
        double pi = s * 4.0;
        long el = System.nanoTime() - t0;
        System.out.printf("%.6f\n", pi);
        System.out.println("T");
        System.out.println(el);
    }
}
