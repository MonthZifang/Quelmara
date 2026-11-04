// b12_gcd —— 整数：3000 万次辗转相除
public class B12Gcd {
    static long gcd(long a, long b) {
        while (b != 0) { long t = b; b = a % b; a = t; }
        return a;
    }
    public static void main(String[] args) {
        long n = 30000000;
        long t0 = System.nanoTime();
        long s = 0;
        for (long i = 1; i <= n; i++) s += gcd(i, 1000000 - i);
        long t1 = System.nanoTime();
        System.out.println(s);
        System.out.println("T");
        System.out.println(t1 - t0);
    }
}
