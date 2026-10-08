// Benchmark 6: loops with data-dependent early exit (break), linear search.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int table[600];
int main() {
  seed = input();
  int n = 600;
  for (int i = 0; i < n; i++) table[i] = rnd() % 4000;
  int found = 0; int missed = 0; int probes = 0; int lastPos = -1; int bestPos = n;
  for (int q = 0; q < 120; q++) {
    int key = rnd() % 4000;
    int pos = -1;
    for (int i = 0; i < n; i++) {
      probes++;
      if (table[i] == key || table[i] % 97 == key % 97) { pos = i; break; }
    }
    if (pos >= 0) {
      found++;
      lastPos = pos;
      if (pos < bestPos) bestPos = pos;
    } else {
      missed++;
    }
  }
  print(found); print(missed); print(probes); print(lastPos); print(bestPos);
  return 0;
}
