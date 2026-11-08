// b4_array —— 数组写入 + 顺序遍历 + 跨步遍历（200 万元素）
class Main {
    public static void main(String[] args) {
        long n = 2000000;
        long[] v = new long[(int) n];
        for (long i = 0; i < n; i++) v[(int) i] = i * 3 + 1;
        long s = 0;
        for (long i = 0; i < n; i++) s += v[(int) i];
        long t = 0;
        for (long i = 0; i < n; i += 7) t += v[(int) i];
        long t0 = System.nanoTime();
        long el = System.nanoTime() - t0;
        System.out.println(s);
        System.out.println(t);
        System.out.println("T");
        System.out.println(el);
    }
}
