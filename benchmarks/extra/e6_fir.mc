// Extra 6: FIR filter with saturation over a noisy signal (after BEEBS fir).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int coef[16];
int sig[700];
int main() {
  seed = input();
  int spikes = input();
  for (int i = 0; i < 16; i++) coef[i] = rnd() % 64 - 32;
  for (int i = 0; i < 700; i++) {
    sig[i] = rnd() % 200 - 100;
    if (rnd() % 1000 < spikes) sig[i] = sig[i] * 50;
  }
  int energy = 0; int clipHi = 0; int clipLo = 0; int peak = 0;
  for (int rep = 0; rep < 3; rep++) {
    for (int i = 16; i < 700; i++) {
      int acc = 0;
      for (int t = 0; t < 16; t++) acc += coef[t] * sig[i - t];
      acc = acc / 64;
      if (acc > 2000) { acc = 2000; clipHi++; }
      else if (acc < -2000) { acc = -2000; clipLo++; }
      if (acc > peak) peak = acc;
      energy += acc * acc % 4096;
    }
  }
  print(energy); print(clipHi); print(clipLo); print(peak);
  return 0;
}
