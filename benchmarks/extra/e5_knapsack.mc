// Extra 5: 0/1 knapsack by dynamic programming over random items.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int wt[60];
int val[60];
int best[501];
int main() {
  seed = input();
  int heavy = input();
  int n = 60; int cap = 500;
  for (int i = 0; i < n; i++) {
    if (rnd() % 100 < heavy) wt[i] = 100 + rnd() % 300; else wt[i] = 1 + rnd() % 40;
    val[i] = 1 + rnd() % 100;
  }
  for (int c = 0; c <= cap; c++) best[c] = 0;
  int updates = 0;
  for (int i = 0; i < n; i++) {
    int w = wt[i]; int v = val[i];
    for (int c = cap; c >= w; c--) {
      int cand = best[c - w] + v;
      if (cand > best[c]) { best[c] = cand; updates++; }
    }
  }
  print(best[cap]); print(updates);
  return 0;
}
