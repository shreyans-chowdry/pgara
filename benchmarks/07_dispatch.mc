// Benchmark 7: switch-heavy bytecode interpreter (if-else dispatch ladder) for a
// small stack machine; opcode frequencies are highly skewed.
int seed;
int rnd() {
  seed = seed * 1103515245 + 12345;
  int r = (seed / 65536) % 32768;
  if (r < 0) r = -r;
  return r;
}
int prog[400];
int stack[64];
int main() {
  seed = input();
  int skew = input();
  int n = 400;
  for (int i = 0; i < n; i++) {
    int r = rnd() % 100;
    if (r < skew) prog[i] = 0;
    else if (r < skew + (100 - skew) / 2) prog[i] = 1;
    else prog[i] = 2 + r % 5;
  }
  int sp = 0; int acc = 0; int pushes = 0; int adds = 0; int muls = 0; int pops = 0; int swaps = 0; int dups = 0;
  for (int rep = 0; rep < 6; rep++) {
    for (int pc = 0; pc < n; pc++) {
      int op = prog[pc];
      if (op == 0) {
        if (sp < 63) { stack[sp] = pc % 17; sp++; }
        pushes++;
      } else if (op == 1) {
        if (sp >= 2) { stack[sp - 2] = (stack[sp - 2] + stack[sp - 1]) % 10007; sp--; }
        adds++;
      } else if (op == 2) {
        if (sp >= 2) { stack[sp - 2] = stack[sp - 2] * stack[sp - 1] % 10007; sp--; }
        muls++;
      } else if (op == 3) {
        if (sp >= 1) { acc = (acc + stack[sp - 1]) % 100003; sp--; }
        pops++;
      } else if (op == 4) {
        if (sp >= 2) { int t = stack[sp - 1]; stack[sp - 1] = stack[sp - 2]; stack[sp - 2] = t; }
        swaps++;
      } else {
        if (sp >= 1 && sp < 63) { stack[sp] = stack[sp - 1]; sp++; }
        dups++;
      }
    }
  }
  print(acc); print(sp); print(pushes); print(adds); print(muls); print(pops); print(swaps); print(dups);
  return 0;
}
