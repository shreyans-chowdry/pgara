// Extra 3: single-source shortest paths on a dense random graph (after MiBench network/dijkstra).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int adj[1600];
int dist[40];
int done[40];
int main() {
  seed = input();
  int n = 40;
  int sparsity = input();
  for (int i = 0; i < n * n; i++) {
    if (rnd() % 100 < sparsity) adj[i] = 0; else adj[i] = 1 + rnd() % 50;
  }
  int checksum = 0; int relax = 0;
  for (int src = 0; src < 12; src++) {
    for (int i = 0; i < n; i++) { dist[i] = 1000000; done[i] = 0; }
    dist[src] = 0;
    for (int it = 0; it < n; it++) {
      int best = -1; int bd = 1000000;
      for (int i = 0; i < n; i++)
        if (done[i] == 0 && dist[i] < bd) { bd = dist[i]; best = i; }
      if (best < 0) break;
      done[best] = 1;
      int row = best * n;
      for (int j = 0; j < n; j++) {
        int w = adj[row + j];
        if (w > 0 && done[j] == 0 && bd + w < dist[j]) { dist[j] = bd + w; relax++; }
      }
    }
    for (int i = 0; i < n; i++) if (dist[i] < 1000000) checksum += dist[i];
  }
  print(checksum); print(relax);
  return 0;
}
