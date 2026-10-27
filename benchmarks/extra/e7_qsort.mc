// Extra 7: recursive quicksort with median-of-three and an insertion-sort cutoff (after MiBench qsort).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int a[600];
int swaps;
void isort(int lo, int hi) {
  for (int i = lo + 1; i <= hi; i++) {
    int key = a[i]; int j = i - 1;
    while (j >= lo && a[j] > key) { a[j + 1] = a[j]; j--; swaps++; }
    a[j + 1] = key;
  }
}
void qs(int lo, int hi) {
  if (hi - lo < 10) { isort(lo, hi); return; }
  int mid = (lo + hi) / 2;
  int x = a[lo]; int y = a[mid]; int z = a[hi];
  int p = y;
  if ((x <= y && y <= z) || (z <= y && y <= x)) p = y;
  else if ((y <= x && x <= z) || (z <= x && x <= y)) p = x;
  else p = z;
  int i = lo; int j = hi;
  while (i <= j) {
    while (a[i] < p) i++;
    while (a[j] > p) j--;
    if (i <= j) { int t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; swaps++; }
  }
  if (lo < j) qs(lo, j);
  if (i < hi) qs(i, hi);
}
int main() {
  seed = input();
  int dup = input();
  int n = 600;
  for (int i = 0; i < n; i++) a[i] = rnd() % dup;
  swaps = 0;
  qs(0, n - 1);
  int ok = 1;
  for (int i = 1; i < n; i++) if (a[i - 1] > a[i]) ok = 0;
  print(ok); print(swaps); print(a[0]); print(a[n / 2]); print(a[n - 1]);
  return 0;
}
