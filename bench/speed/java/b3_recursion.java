// b3_recursion —— 朴素递归 fib(30)
class Main {
    static long fib(long n) {
        if (n < 2) return n;
        return fib(n - 1) + fib(n - 2);
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long r = fib(30);
        long el = System.nanoTime() - t0;
        System.out.println(r);
        System.out.println("T");
        System.out.println(el);
    }
}
