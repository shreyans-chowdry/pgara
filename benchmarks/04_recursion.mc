// Benchmark 4: recursion (Fibonacci and Ackermann-style calls), MDP across call boundaries.
int fib(int n) {
  if (n < 2) return n;
  return fib(n - 1) + fib(n - 2);
}
int gcd(int a, int b) {
  if (b == 0) return a;
  return gcd(b, a % b);
}
int power(int base, int e, int m) {
  if (e == 0) return 1;
  int half = power(base, e / 2, m);
  int sq = half * half % m;
  if (e % 2 == 1) return sq * base % m;
  return sq;
}
int main() {
  int n = input();
  int f = fib(n);
  int g = 0;
  for (int i = 1; i < 60; i++) g += gcd(f + i * 37, i * 1001 + 17);
  int p = 0;
  for (int i = 1; i < 40; i++) p = (p + power(i + n, 1000 + i, 9973)) % 9973;
  print(f); print(g); print(p);
  return 0;
}
