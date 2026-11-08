// b78_sum_digits
class Main {
    static long digit_sum(long n) {
        long s = 0;
        while (n > 0) { s += n % 10; n /= 10; }
        return s;
    }
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 1000000; i++) acc += digit_sum(i);
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
