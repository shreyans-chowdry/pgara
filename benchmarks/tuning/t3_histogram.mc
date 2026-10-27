// Tuning 3: histogram with outlier handling on skewed data.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int hist[32];
int main() {
  seed = input();
  int outl = input();
  int under = 0; int over = 0; int sum = 0; int big = 0;
  for (int i = 0; i < 32; i++) hist[i] = 0;
  for (int i = 0; i < 6000; i++) {
    int x = rnd() % 320;
    if (rnd() % 1000 < outl) x = x * 7 - 900;
    if (x < 0) { under++; big += -x; }
    else if (x >= 320) { over++; big += x; }
    else { int h = x / 10; hist[h] = hist[h] + 1; sum += x; }
  }
  int mode = 0;
  for (int i = 1; i < 32; i++) if (hist[i] > hist[mode]) mode = i;
  print(under); print(over); print(sum); print(big); print(mode);
  return 0;
}
