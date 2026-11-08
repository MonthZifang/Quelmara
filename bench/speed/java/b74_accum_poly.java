// b74_accum_poly
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long n = 1; n <= 5000000; n++) {
            long s = 0;
            for (int k = 0; k < 5; k++) s = s * n + k * 3 + 1;
            acc += s % 1000003;
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc % 1000003);
        System.out.println("T");
        System.out.println(el);
    }
}
