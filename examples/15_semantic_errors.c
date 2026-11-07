/* Демонстрація семантичних помилок (синтаксично програма коректна) */
#include <stdio.h>

int square(int x) { return x * x; }

void nothing() { return 5; }

int main() {
    int a = 5;
    int a = 6;                 /* повторне оголошення */
    b = 10;                    /* неоголошена змінна */
    square(1, 2);              /* неправильна кількість аргументів */
    undefined_func(3);         /* неоголошена функція */
    5 = a;                     /* не lvalue */
    float f = 2.5;
    int r = f % 2;             /* % для дійсних */
    break;                     /* break поза циклом */
    return 0;
}
