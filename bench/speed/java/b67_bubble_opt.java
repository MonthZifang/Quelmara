// b67_bubble_opt
class Main {
    public static void main(String[] args) {
        long n = 5000;
        long[] a = new long[(int) n];
        long seed = 99;
        for (long i = 0; i < n; i++) { seed = (seed * 1103515245L + 12345) % 2147483648L; a[(int) i] = seed % 100000; }
        long t0 = System.nanoTime();
        int swapped = 1;
        while (swapped == 1) {
            swapped = 0;
            for (long j = 0; j < n - 1; j++)
                if (a[(int) j] > a[(int) (j + 1)]) { long t = a[(int) j]; a[(int) j] = a[(int) (j + 1)]; a[(int) (j + 1)] = t; swapped = 1; }
        }
        long el = System.nanoTime() - t0;
        System.out.println(a[0]);
        System.out.println("T");
        System.out.println(el);
    }
}
