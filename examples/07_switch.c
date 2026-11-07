/* switch/case з fallthrough, default, break та continue всередині switch */
#include <stdio.h>

int days_in_month(int m) {
    switch (m) {
        case 2:
            return 28;
        case 4: case 6: case 9: case 11:
            return 30;
        default:
            return 31;
    }
}

int main() {
    for (int m = 1; m <= 12; m++)
        printf("%d:%d ", m, days_in_month(m));
    printf("\n");

    int score = 0;
    for (int i = 0; i < 8; i++) {
        switch (i % 4) {
            case 0:
                score += 1;          /* fallthrough */
            case 1:
                score += 10;
                break;
            case 2:
                continue;            /* continue зовнішнього циклу */
            default:
                score += 100;
        }
        printf("i=%d score=%d\n", i, score);
    }
    char op = '*';
    int x = 6, y = 7, r;
    switch (op) {
        case '+': r = x + y; break;
        case '-': r = x - y; break;
        case '*': r = x * y; break;
        default: r = 0;
    }
    printf("%d %c %d = %d\n", x, op, y, r);
    return 0;
}
