// b32_io_write
class Main {
    public static void main(String[] args) {
        long n = 1000000;
        long[] buf = new long[(int) n];
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) buf[(int) i] = i * 2 + 1;
        long el = System.nanoTime() - t0;
        System.out.println(buf[(int) (n - 1)]);
        System.out.println("T");
        System.out.println(el);
    }
}
