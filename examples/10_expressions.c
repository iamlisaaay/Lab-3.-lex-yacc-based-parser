/* Пріоритети та асоціативність операторів, побітові операції, приведення типів, sizeof */
#include <stdio.h>

int main() {
    int a = 10, b = 3, c;
    printf("2 + 3 * 4 = %d\n", 2 + 3 * 4);
    printf("(2 + 3) * 4 = %d\n", (2 + 3) * 4);
    printf("10 - 4 - 3 = %d\n", 10 - 4 - 3);                 /* ліва асоціативність */
    printf("100 / 10 / 5 = %d\n", 100 / 10 / 5);
    printf("-7 / 2 = %d, -7 %% 2 = %d\n", -7 / 2, -7 % 2);   /* округлення до нуля */
    a = b = c = 4;                                           /* права асоціативність */
    printf("a = b = c = 4 -> %d %d %d\n", a, b, c);
    a = 10;
    printf("a & 6 = %d, a | 5 = %d, a ^ 3 = %d, ~a = %d\n", a & 6, a | 5, a ^ 3, ~a);
    printf("1 << 10 = %d, 1024 >> 3 = %d\n", 1 << 10, 1024 >> 3);
    printf("a > 5 && b < 5 = %d, !a = %d, a == 10 || 0 = %d\n", a > 5 && b < 5, !a, a == 10 || 0);
    printf("1 < 2 < 3 = %d, 3 > 2 > 1 = %d\n", 1 < 2 < 3, 3 > 2 > 1);  /* як у C, не як у Python */
    double d = 7.9;
    int t = (int)d;
    printf("(int)7.9 = %d, (double)7/2 = %.2f, 7/2 = %d\n", t, (double)7 / 2, 7 / 2);
    printf("sizeof(int) = %d, sizeof(double) = %d, sizeof(char) = %d\n",
           (int)sizeof(int), (int)sizeof(double), (int)sizeof(char));
    int k = 5;
    int m = k++ * 10;                                        /* постфіксний: спочатку 5 */
    m += ++k;                                                /* префіксний: 7 */
    printf("k = %d, m = %d\n", k, m);
    int x = 17;
    x += 3; x -= 2; x *= 2; x /= 4; x %= 5; x <<= 2; x |= 1;
    printf("compound: x = %d\n", x);
    char ch = 'A' + 2;
    printf("ch = %c (%d)\n", ch, ch);
    printf("ternary: %s\n", a > b ? "a > b" : "a <= b");
    int i, j;
    for (i = 0, j = 10; i < j; i += 3, j -= 3)               /* оператор кома */
        ;
    printf("comma: i = %d, j = %d\n", i, j);
    return 0;
}
