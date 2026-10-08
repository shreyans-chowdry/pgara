// Benchmark 9: insertion sort followed by binary searches (data-dependent swaps).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int a[300];
int main() {
  seed = input();
  int n = 300;
  for (int i = 0; i < n; i++) a[i] = rnd() % 10000;
  int shifts = 0;
  for (int i = 1; i < n; i++) {
    int key = a[i];
    int j = i - 1;
    while (j >= 0 && a[j] > key) { a[j + 1] = a[j]; j--; shifts++; }
    a[j + 1] = key;
  }
  int hits = 0; int steps = 0;
  for (int q = 0; q < 400; q++) {
    int key = rnd() % 10000;
    int lo = 0; int hi = n - 1;
    while (lo <= hi) {
      int mid = (lo + hi) / 2;
      steps++;
      if (a[mid] == key) { hits++; break; }
      if (a[mid] < key) lo = mid + 1; else hi = mid - 1;
    }
  }
  print(shifts); print(hits); print(steps); print(a[0]); print(a[n - 1]);
  return 0;
}
