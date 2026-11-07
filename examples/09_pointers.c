/* Вказівники: &, *, арифметика вказівників, swap через вказівники.
   Повністю підтримується інтерпретатором AST та генератором TAC.
   У Python/JS немає адрес змінних, тому трансляція &x / *p повідомляє про обмеження. */
#include <stdio.h>

void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

int sum(int *p, int n) {
    int s = 0;
    for (int i = 0; i < n; i++)
        s += *(p + i);
    return s;
}

int main() {
    int x = 5, y = 10;
    swap(&x, &y);
    printf("after swap: x = %d, y = %d\n", x, y);

    int arr[5] = {1, 2, 3, 4, 5};
    int *p = arr;
    *(p + 2) = 30;
    p++;
    *p = 20;
    printf("arr = %d %d %d %d %d\n", arr[0], arr[1], arr[2], arr[3], arr[4]);
    printf("sum = %d\n", sum(arr, 5));

    int *q = &arr[4];
    printf("q - p = %d, *q = %d\n", (int)(q - p), *q);

    /* інтерпретатор емулює 32-бітний int: переповнення як у C */
    int big = 2147483647;
    big = big + 1;
    printf("INT_MAX + 1 = %d\n", big);
    unsigned int u = 0;
    u = u - 1;
    printf("(unsigned)0 - 1 = %u\n", u);
    return 0;
}
