// Benchmark 5: hot loop with a rare, data-dependent error branch (the worked example).
// The error path touches several values; static priors treat it as a 50/50 branch.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int data[1024];
int main() {
  seed = input();
  int threshold = input();
  int n = 1024;
  for (int i = 0; i < n; i++) {
    int r = rnd();
    if (r % 1000 < threshold) data[i] = -(r % 50) - 1; else data[i] = r % 200;
  }
  int sum = 0; int weighted = 0; int cnt = 0; int peak = 0;
  int errCount = 0; int errSum = 0; int lastErr = -1; int errSpan = 0;
  for (int rep = 0; rep < 4; rep++) {
    for (int i = 0; i < n; i++) {
      int x = data[i];
      if (x < 0) {
        errCount++;
        errSum += x;
        if (lastErr >= 0) errSpan += i - lastErr;
        lastErr = i;
      } else {
        sum += x * 2;
        weighted += x * (i % 7);
        cnt++;
        if (x > peak) peak = x;
      }
    }
  }
  print(sum); print(weighted); print(cnt); print(peak);
  print(errCount); print(errSum); print(lastErr); print(errSpan);
  return 0;
}
