// b38_prime
class Main {
    static int is_prime(long n) {
        if (n < 2) return 0;
        if (n == 2) return 1;
        if (n % 2 == 0) return 0;
        for (long d = 3; d * d <= n; d += 2)
            if (n % d == 0) return 0;
        return 1;
    }
    public static void main(String[] args) {
        long cnt = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 100000; i++) if (is_prime(i) == 1) cnt++;
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
