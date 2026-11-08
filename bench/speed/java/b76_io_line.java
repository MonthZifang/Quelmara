// b76_io_line
class Main {
    public static void main(String[] args) {
        long n = 1000000;
        long[] lines = new long[(int) n];
        for (long i = 0; i < n; i++) lines[(int) i] = i * 7 + 3;
        long sum = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < n; j++) sum += lines[(int) j] % 100;
        long el = System.nanoTime() - t0;
        System.out.println(sum);
        System.out.println("T");
        System.out.println(el);
    }
}
