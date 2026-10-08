// Benchmark 2: regular hot loop over an array with several accumulators.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int data[512];
int main() {
  seed = input();
  int n = 512;
  for (int i = 0; i < n; i++) data[i] = rnd() % 1000;
  int sum = 0; int sumsq = 0; int mn = 1000000; int mx = -1; int odd = 0;
  for (int rep = 0; rep < 8; rep++) {
    for (int i = 0; i < n; i++) {
      int x = data[i];
      sum += x;
      sumsq += x * x % 1024;
      if (x < mn) mn = x;
      if (x > mx) mx = x;
      odd += x % 2;
    }
  }
  print(sum); print(sumsq); print(mn); print(mx); print(odd);
  return 0;
}
