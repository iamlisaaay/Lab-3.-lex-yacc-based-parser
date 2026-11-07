/* Решето Ератосфена, break/continue, логічні оператори */
#include <stdio.h>
#define MAX 100

int sieve[MAX + 1];

int is_prime(int n) {
    if (n < 2) return 0;
    for (int d = 2; d * d <= n; d++)
        if (n % d == 0) return 0;
    return 1;
}

int main() {
    int count = 0;
    for (int i = 2; i <= MAX; i++) sieve[i] = 1;
    for (int i = 2; i * i <= MAX; i++) {
        if (!sieve[i]) continue;
        for (int j = i * i; j <= MAX; j += i)
            sieve[j] = 0;
    }
    printf("Primes up to %d:", MAX);
    for (int i = 0; i <= MAX; i++) {
        if (sieve[i]) {
            printf(" %d", i);
            count++;
        }
    }
    printf("\nTotal: %d\n", count);

    /* перше просте число > 1000, у якого сума цифр теж проста і > 10 */
    int n = 1000;
    while (1) {
        n++;
        if (!is_prime(n)) continue;
        int s = 0, m = n;
        while (m > 0) { s += m % 10; m /= 10; }
        if (is_prime(s) && s > 10) break;
    }
    printf("First prime > 1000 with prime digit sum > 10: %d\n", n);
    return 0;
}
