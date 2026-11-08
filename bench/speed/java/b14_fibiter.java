// b14_fibiter —— 迭代 fib(5000 万)
class Main {
    public static void main(String[] args) {
        long n = 50000000;
        long a = 0, b = 1;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) {
            long t = a + b;
            a = b;
            b = t % 1000000007;
        }
        long el = System.nanoTime() - t0;
        System.out.println(a);
        System.out.println("T");
        System.out.println(el);
    }
}
