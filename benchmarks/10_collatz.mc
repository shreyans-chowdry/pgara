// Benchmark 10: Collatz trajectories and a prime sieve (irregular integer control flow).
int sieve[3000];
int main() {
  int limit = input();
  int longest = 0; int arg = 0; int totalSteps = 0; int peak = 0;
  for (int s = 1; s < limit; s++) {
    int x = s; int steps = 0;
    while (x != 1) {
      if (x % 2 == 0) x = x / 2; else x = 3 * x + 1;
      if (x > peak) peak = x;
      steps++;
    }
    totalSteps += steps;
    if (steps > longest) { longest = steps; arg = s; }
  }
  int primes = 0;
  for (int i = 2; i < 3000; i++) {
    if (sieve[i] == 0) {
      primes++;
      for (int j = i * i; j < 3000; j += i) sieve[j] = 1;
    }
  }
  print(longest); print(arg); print(totalSteps); print(peak); print(primes);
  return 0;
}
