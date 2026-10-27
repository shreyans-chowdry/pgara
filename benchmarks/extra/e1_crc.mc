// Extra 1: bitwise CRC-32 over a pseudo-random message (after MiBench telecomm/CRC32),
// with shifts and XOR expressed arithmetically because MiniC has no bit operators.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int msg[256];
int main() {
  seed = input();
  int len = input();
  for (int i = 0; i < len; i++) msg[i] = rnd() % 256;
  int crc = 65535; int poly = 40961; int flips = 0;
  for (int pass = 0; pass < 6; pass++) {
    for (int i = 0; i < len; i++) {
      int byte = msg[i];
      for (int b = 0; b < 8; b++) {
        int bit = (crc + byte) % 2;
        crc = crc / 2;
        if (bit == 1) {
          // crc ^= poly, bit by bit on 16-bit values
          int x = crc; int y = poly; int r = 0; int p = 1;
          for (int j = 0; j < 16; j++) {
            if ((x % 2) != (y % 2)) r += p;
            x = x / 2; y = y / 2; p = p * 2;
          }
          crc = r; flips++;
        }
        byte = byte / 2;
      }
    }
  }
  print(crc); print(flips);
  return 0;
}
