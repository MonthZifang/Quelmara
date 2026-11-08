// b5_string —— 20 万次 int→str→int
class Main {
    public static void main(String[] args) {
        long n = 500000, acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < n; i++) {
            String buf = Long.toString(i);
            acc += buf.length();
            acc += Long.parseLong(buf);
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
