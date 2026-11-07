/* Найпростіша програма: виведення та арифметика */
#include <stdio.h>

int main() {
    int a = 7, b = 3;
    printf("Hello, MiniC!\n");
    printf("%d + %d = %d\n", a, b, a + b);
    printf("%d / %d = %d, %d %% %d = %d\n", a, b, a / b, a, b, a % b);
    printf("7.0 / 2 = %.2f\n", 7.0 / 2);
    return 0;
}
