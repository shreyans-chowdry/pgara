// Tuning 5: gcd and lcm table with a rare overflow guard.
int gcd(int a, int b) {
  while (b != 0) { int t = a % b; a = b; b = t; }
  return a;
}
int main() {
  int n = input();
  int sumg = 0; int coprime = 0; int capped = 0; int suml = 0;
  for (int i = 1; i <= n; i++) {
    for (int j = 1; j <= n; j++) {
      int g = gcd(i, j);
      sumg += g;
      if (g == 1) coprime++;
      int l = i / g * j;
      if (l > 900) { capped++; l = 900; }
      suml += l;
    }
  }
  print(sumg); print(coprime); print(capped); print(suml);
  return 0;
}
