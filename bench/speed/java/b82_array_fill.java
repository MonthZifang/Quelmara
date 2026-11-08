// b82_array_fill
class Main {
    public static void main(String[] args) {
        long n = 5000000;
        long[] a = new long[(int) n];
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) a[(int) i] = i * 2 + 1;
        long el = System.nanoTime() - t0;
        System.out.println(a[(int) (n - 1)]);
        System.out.println("T");
        System.out.println(el);
    }
}
