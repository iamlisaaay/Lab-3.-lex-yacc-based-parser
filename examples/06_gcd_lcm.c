/* НСД/НСК: алгоритм Евкліда (рекурсивний та ітеративний), тернарний оператор */
#include <stdio.h>

int gcd(int a, int b) {
    return b == 0 ? a : gcd(b, a % b);
}

int gcd_iter(int a, int b) {
    while (b != 0) {
        int t = a % b;
        a = b;
        b = t;
    }
    return a;
}

int lcm(int a, int b) { return a / gcd(a, b) * b; }

int main() {
    int pairs[4][2] = {{48, 18}, {270, 192}, {17, 5}, {100, 75}};
    for (int i = 0; i < 4; i++) {
        int a = pairs[i][0], b = pairs[i][1];
        printf("gcd(%d, %d) = %d = %d, lcm = %d\n", a, b, gcd(a, b), gcd_iter(a, b), lcm(a, b));
    }
    return 0;
}
