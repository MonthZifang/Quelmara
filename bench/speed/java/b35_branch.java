// b35_branch
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 20000000; i++) {
            if ((i & 3) == 0) acc += 1; else acc -= 1;
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
