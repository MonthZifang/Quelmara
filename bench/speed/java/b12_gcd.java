// b12_gcd —— GCD 密集：3000 万次辗转相除
class Main {
    static long gcd(long a, long b) {
        while (b != 0) { long t = b; b = a % b; a = t; }
        return a;
    }
    public static void main(String[] args) {
        long n = 30000000;
        long s = 0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= n; i++) s += gcd(i, 1000000 - i);
        long el = System.nanoTime() - t0;
        System.out.println(s);
        System.out.println("T");
        System.out.println(el);
    }
}
