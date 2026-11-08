// b45_accumulate
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long n = 1; n <= 1000000; n++) {
            long s = 0;
            for (int k = 0; k < 10; k++) s = s * n + k;
            acc += s % 1000003;
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
