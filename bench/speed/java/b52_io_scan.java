// b52_io_scan
class Main {
    public static void main(String[] args) {
        long n = 1000000;
        long[] buf = new long[(int) n];
        for (long i = 0; i < n; i++) buf[(int) i] = i * 3 + 1;
        long sum = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < n; j++) sum += buf[(int) j];
        long el = System.nanoTime() - t0;
        System.out.println(sum);
        System.out.println("T");
        System.out.println(el);
    }
}
