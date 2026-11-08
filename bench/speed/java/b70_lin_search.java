// b70_lin_search
class Main {
    public static void main(String[] args) {
        long n = 1000;
        long[] a = new long[(int) n];
        for (long i = 0; i < n; i++) a[(int) i] = i * 3 + 7;
        long found = 0;
        long t0 = System.nanoTime();
        for (long j = 0; j < 1000000; j++) {
            long target = (j * 37 + 11) % 3000;
            for (long k = 0; k < n; k++) if (a[(int) k] == target) found++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(found);
        System.out.println("T");
        System.out.println(el);
    }
}
