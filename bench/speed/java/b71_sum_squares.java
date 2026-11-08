// b71_sum_squares
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 1; i <= 1000000; i++) acc += i * i;
        long el = System.nanoTime() - t0;
        System.out.println(acc % 1000003);
        System.out.println("T");
        System.out.println(el);
    }
}
