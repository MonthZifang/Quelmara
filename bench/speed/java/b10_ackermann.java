// b10_ackermann —— Ackermann(2,8)
class Main {
    static long ack(long m, long n) {
        if (m == 0) return n + 1;
        if (n == 0) return ack(m - 1, 1);
        return ack(m - 1, ack(m, n - 1));
    }
    public static void main(String[] args) {
        long t0 = System.nanoTime();
        long r = ack(2, 8);
        long el = System.nanoTime() - t0;
        System.out.println(r);
        System.out.println("T");
        System.out.println(el);
    }
}
