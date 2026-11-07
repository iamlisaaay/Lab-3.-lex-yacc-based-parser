/* Рекурсія та цикл: факторіал */
#include <stdio.h>

long factorial(int n) {
    if (n <= 1)
        return 1;
    return n * factorial(n - 1);
}

long factorial_iter(int n) {
    long result = 1;
    for (int i = 2; i <= n; i++)
        result *= i;
    return result;
}

int main() {
    for (int i = 0; i <= 12; i++) {
        printf("%2d! = %ld (iter: %ld)\n", i, factorial(i), factorial_iter(i));
    }
    return 0;
}
