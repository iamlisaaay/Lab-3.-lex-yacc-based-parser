/* Масиви та цикли: числа Фібоначчі */
#include <stdio.h>
#define N 20

int fib[N];

int fib_rec(int n) {
    return n < 2 ? n : fib_rec(n - 1) + fib_rec(n - 2);
}

int main() {
    fib[0] = 0;
    fib[1] = 1;
    for (int i = 2; i < N; ++i)
        fib[i] = fib[i - 1] + fib[i - 2];

    printf("Fibonacci:");
    for (int i = 0; i < N; i++)
        printf(" %d", fib[i]);
    printf("\n");
    printf("fib_rec(15) = %d\n", fib_rec(15));
    return 0;
}
