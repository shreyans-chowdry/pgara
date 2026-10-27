// Extra 4: edit distance between random strings over a small alphabet (after BEEBS levenshtein).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int s1[64];
int s2[64];
int prev[65];
int cur[65];
int main() {
  seed = input();
  int alpha = input();
  int total = 0; int matches = 0;
  for (int t = 0; t < 12; t++) {
    int n = 40 + rnd() % 24; int m = 40 + rnd() % 24;
    for (int i = 0; i < n; i++) s1[i] = rnd() % alpha;
    for (int j = 0; j < m; j++) s2[j] = rnd() % alpha;
    for (int j = 0; j <= m; j++) prev[j] = j;
    for (int i = 1; i <= n; i++) {
      cur[0] = i;
      int a = s1[i - 1];
      for (int j = 1; j <= m; j++) {
        int cost = 1;
        if (a == s2[j - 1]) { cost = 0; matches++; }
        int best = prev[j - 1] + cost;
        int del = prev[j] + 1;
        int ins = cur[j - 1] + 1;
        if (del < best) best = del;
        if (ins < best) best = ins;
        cur[j] = best;
      }
      for (int j = 0; j <= m; j++) prev[j] = cur[j];
    }
    total += prev[m];
  }
  print(total); print(matches);
  return 0;
}
