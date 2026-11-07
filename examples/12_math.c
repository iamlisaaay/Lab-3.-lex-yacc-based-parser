/* Дійсні числа: метод Ньютона, ряд Тейлора для e, вбудовані функції math.h */
#include <stdio.h>
#include <math.h>

double my_sqrt(double x) {
    double g = x / 2.0;
    for (int i = 0; i < 20; i++)
        g = (g + x / g) / 2.0;
    return g;
}

double my_exp(double x) {
    double term = 1.0, sum = 1.0;
    for (int n = 1; n < 30; n++) {
        term *= x / n;
        sum += term;
    }
    return sum;
}

int main() {
    for (int i = 2; i <= 10; i += 2)
        printf("sqrt(%d): newton = %.6f, libm = %.6f\n", i, my_sqrt(i), sqrt(i));
    printf("e = %.10f\n", my_exp(1.0));
    printf("pow(2, 10) = %.0f, fabs(-3.5) = %.1f, floor(2.7) = %.0f, ceil(2.1) = %.0f\n",
           pow(2, 10), fabs(-3.5), floor(2.7), ceil(2.1));
    double celsius;
    for (celsius = -10; celsius <= 40; celsius += 12.5)
        printf("%6.1f C = %6.1f F\n", celsius, celsius * 9 / 5 + 32);
    return 0;
}
