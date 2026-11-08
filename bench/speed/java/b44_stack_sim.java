// b44_stack_sim
class Main {
    public static void main(String[] args) {
        long[] st = new long[1000000];
        long top = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 1000000; i++) {
            st[(int) (top++)] = i;
            if (i % 3 == 0 && top > 0) st[(int) (top - 1)]++;
        }
        long el = System.nanoTime() - t0;
        System.out.println(st[(int) (top - 1)]);
        System.out.println("T");
        System.out.println(el);
    }
}
