// Benchmark 3: nested loops (dense matrix multiply, N x N stored row-major).
int A[256];
int B[256];
int C[256];
int main() {
  int n = 16;
  int s = input();
  for (int i = 0; i < n * n; i++) {
    A[i] = (i * 7 + s) % 13 - 6;
    B[i] = (i * 5 + 2 * s) % 11 - 5;
  }
  for (int r = 0; r < 3; r++) {
    for (int i = 0; i < n; i++) {
      for (int j = 0; j < n; j++) {
        int acc = 0;
        for (int k = 0; k < n; k++) {
          acc += A[i * n + k] * B[k * n + j];
        }
        C[i * n + j] = acc + r;
      }
    }
  }
  int trace = 0; int total = 0;
  for (int i = 0; i < n; i++) trace += C[i * n + i];
  for (int i = 0; i < n * n; i++) total += C[i];
  print(trace); print(total);
  return 0;
}
