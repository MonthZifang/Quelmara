// b73_graph_bfs
class Main {
    public static void main(String[] args) {
        long n = 1000;
        long[] adj = new long[(int) (n * n)];
        long seed = 55;
        for (long e = 0; e < 5000; e++) {
            seed = (seed * 1103515245L + 12345) % 2147483648L; long u = seed % n;
            seed = (seed * 1103515245L + 12345) % 2147483648L; long v = seed % n;
            adj[(int) (u * n + v)] = 1;
        }
        long[] visited = new long[(int) n];
        long[] queue = new long[(int) n];
        long front = 0, back = 0;
        queue[(int) (back++)] = 0; visited[0] = 1;
        long cnt = 0;
        long t0 = System.nanoTime();
        while (front < back) {
            long u = queue[(int) (front++)];
            cnt++;
            for (long v = 0; v < n; v++)
                if (adj[(int) (u * n + v)] != 0 && visited[(int) v] == 0) { visited[(int) v] = 1; queue[(int) (back++)] = v; }
        }
        long el = System.nanoTime() - t0;
        System.out.println(cnt);
        System.out.println("T");
        System.out.println(el);
    }
}
