// b57_pow_mod
class Main {
    static long pow_mod(long base, long exp, long mod) {
        long result = 1, b = base % mod;
        while (exp > 0) {
            if (exp % 2 == 1) result = (result * b) % mod;
            b = (b * b) % mod; exp /= 2;
        }
        return result;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= 1000000; i++) acc = (acc + pow_mod(i, i, 1000003)) % 1000003;
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
