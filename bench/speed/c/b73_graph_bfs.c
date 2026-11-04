// b73_graph_bfs
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "bench.h"

int main(void) {
    int64_t n = 1000;
    int64_t *adj = calloc(n * n, 8);
    uint64_t seed = 55;
    for (int64_t e = 0; e < 5000; e++) {
        seed=(seed*1103515245+12345)%2147483648ULL; int64_t u=seed%n;
        seed=(seed*1103515245+12345)%2147483648ULL; int64_t v=seed%n;
        adj[u*n+v]=1;
    }
    T0();
    int64_t *visited = calloc(n, 8);
    int64_t *queue = malloc(n * 8);
    int64_t front = 0, back = 0;
    queue[back++] = 0; visited[0] = 1;
    int64_t cnt = 0;
    while (front < back) {
        int64_t u = queue[front++];
        cnt++;
        for (int64_t v = 0; v < n; v++)
            if (adj[u*n+v] && !visited[v]) { visited[v]=1; queue[back++]=v; }
    }
    T1();
    printf("%lld\n", (long long)cnt);
    TPRINT();
    free(adj); free(visited); free(queue);
    return 0;
}
