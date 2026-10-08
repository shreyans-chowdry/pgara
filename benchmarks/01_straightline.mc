// Benchmark 1: straight-line arithmetic (no branches, P = 1 everywhere).
// Many simultaneously live temporaries create register pressure.
int main() {
  int a = input();
  int b = input();
  int c = a * 3 + b;
  int d = b * 5 - a;
  int e = c * d + 7;
  int f = (a + b) * (c - d);
  int g = e - f + c * 2;
  int h = g * a - d * b + e;
  int i = h + g + f + e + d + c + b + a;
  int j = (i % 97) * (h % 89) + (g % 83);
  print(c); print(d); print(e); print(f);
  print(g); print(h); print(i); print(j);
  print(a * b * c - d * e * f + g * h * i - j);
  return 0;
}
