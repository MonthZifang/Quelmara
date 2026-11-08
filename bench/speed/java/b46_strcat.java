// b46_strcat
class Main {
    public static void main(String[] args) {
        long acc = 0;
        long t0 = System.nanoTime();
        for (long i = 0; i < 100000; i++) {
            String s = "hello" + " " + "world" + " " + "12345";
            acc += s.length();
        }
        long el = System.nanoTime() - t0;
        System.out.println(acc);
        System.out.println("T");
        System.out.println(el);
    }
}
