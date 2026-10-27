// Tuning 2: trial-division prime counting with an occasional twin-prime check.
int main() {
  int lim = input();
  int count = 0; int twins = 0; int last = 2; int maxgap = 0;
  for (int n = 3; n < lim; n += 2) {
    int prime = 1;
    for (int d = 3; d * d <= n; d += 2) if (n % d == 0) { prime = 0; break; }
    if (prime == 1) {
      count++;
      if (n - last == 2) twins++;
      if (n - last > maxgap) maxgap = n - last;
      last = n;
    }
  }
  print(count); print(twins); print(maxgap);
  return 0;
}
