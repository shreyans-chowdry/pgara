// Benchmark 8: data-dependent token scanner over a synthetic character stream.
// Classes: 0-9 digits, 10-35 letters, 36 space, 37-40 punctuation.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int text[2000];
int main() {
  seed = input();
  int digitBias = input();
  int n = 2000;
  for (int i = 0; i < n; i++) {
    int r = rnd() % 100;
    if (r < digitBias) text[i] = rnd() % 10;
    else if (r < 85) text[i] = 10 + rnd() % 26;
    else if (r < 95) text[i] = 36;
    else text[i] = 37 + rnd() % 4;
  }
  int numbers = 0; int idents = 0; int puncts = 0; int value = 0; int maxValue = 0;
  int identLen = 0; int longest = 0; int state = 0; int checksum = 0;
  for (int i = 0; i < n; i++) {
    int c = text[i];
    if (c < 10) {
      if (state == 2) { idents++; if (identLen > longest) longest = identLen; identLen = 0; }
      value = (value * 10 + c) % 1000003;
      state = 1;
    } else if (c < 36) {
      if (state == 1) { numbers++; if (value > maxValue) maxValue = value; checksum = (checksum + value) % 65521; value = 0; }
      identLen++;
      state = 2;
    } else {
      if (state == 1) { numbers++; if (value > maxValue) maxValue = value; checksum = (checksum + value) % 65521; value = 0; }
      if (state == 2) { idents++; if (identLen > longest) longest = identLen; identLen = 0; }
      if (c > 36) puncts++;
      state = 0;
    }
  }
  print(numbers); print(idents); print(puncts); print(maxValue); print(longest); print(checksum);
  return 0;
}
