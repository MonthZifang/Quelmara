// b50_permute
class Main {
    static long perm(long[] arr, int k, int n, long acc) {
        if (k == n) {
            long h = 0;
            for (int i = 0; i < n; i++) h = h * 31 + arr[i];
            return acc + (h % 1000003);
        }
        long s = acc;
        for (int i = k; i < n; i++) {
            long t = arr[k]; arr[k] = arr[i]; arr[i] = t;
            s = perm(arr, k + 1, n, s);
            t = arr[k]; arr[k] = arr[i]; arr[i] = t;
        }
        return s;
    }
    public static void main(String[] args) {
        long[] a = new long[10];
        for (int i = 0; i < 10; i++) a[i] = i + 1;
        long t0 = System.nanoTime();
        long r = perm(a, 0, 10, 0);
        long el = System.nanoTime() - t0;
        System.out.println(r);
        System.out.println("T");
        System.out.println(el);
    }
}
