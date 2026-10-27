// Extra 2: three bit-counting methods compared on random words (after MiBench automotive/bitcount).
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int byteCount[256];
int main() {
  seed = input();
  int n = input();
  for (int i = 0; i < 256; i++) {
    int c = 0; int x = i;
    while (x > 0) { c += x % 2; x = x / 2; }
    byteCount[i] = c;
  }
  int total1 = 0; int total2 = 0; int total3 = 0; int sparse = 0;
  for (int i = 0; i < n; i++) {
    int w = rnd() * 3 + rnd() % 3;
    int x = w;
    while (x > 0) { total1 += x % 2; x = x / 2; }
    x = w; int c = 0;
    while (x > 0) { if (x % 2 == 1) { c++; x = x - 1; } else x = x / 2; }
    total2 += c;
    if (c < 4) sparse++;
    x = w;
    while (x > 0) { total3 += byteCount[x % 256]; x = x / 256; }
  }
  print(total1); print(total2); print(total3); print(sparse);
  return 0;
}
