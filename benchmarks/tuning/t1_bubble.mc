// Tuning 1: bubble sort with early exit.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int a[150];
int main() {
  seed = input();
  int n = 150;
  for (int i = 0; i < n; i++) a[i] = rnd() % 1000;
  int passes = 0; int swaps = 0;
  int sorted = 0;
  while (sorted == 0) {
    sorted = 1; passes++;
    for (int i = 0; i < n - 1; i++)
      if (a[i] > a[i + 1]) { int t = a[i]; a[i] = a[i + 1]; a[i + 1] = t; swaps++; sorted = 0; }
  }
  print(passes); print(swaps); print(a[0]); print(a[n - 1]);
  return 0;
}
