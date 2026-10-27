// Tuning 4: naive substring search over a random text.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int text[2000];
int pat[8];
int main() {
  seed = input();
  int alpha = input();
  for (int i = 0; i < 2000; i++) text[i] = rnd() % alpha;
  int found = 0; int cmps = 0;
  for (int q = 0; q < 6; q++) {
    int m = 3 + q % 4;
    for (int j = 0; j < m; j++) pat[j] = rnd() % alpha;
    for (int i = 0; i + m <= 2000; i++) {
      int j = 0;
      while (j < m && text[i + j] == pat[j]) { j++; cmps++; }
      cmps++;
      if (j == m) found++;
    }
  }
  print(found); print(cmps);
  return 0;
}
