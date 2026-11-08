// b31_memcpy
class Main {
    public static void main(String[] args) {
        long n = 12500000;
        long[] src = new long[(int) n];
        long[] dst = new long[(int) n];
        for (long i = 0; i < n; i++) src[(int) i] = i;
        long t0 = System.nanoTime();
        for (long j = 0; j < n; j++) dst[(int) j] = src[(int) j];
        long el = System.nanoTime() - t0;
        System.out.println(dst[(int) (n - 1)]);
        System.out.println("T");
        System.out.println(el);
    }
}
