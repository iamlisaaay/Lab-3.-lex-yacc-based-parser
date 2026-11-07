/* Ханойські вежі: рекурсія та глобальний лічильник */
#include <stdio.h>

int moves = 0;

void hanoi(int n, char from, char to, char via) {
    if (n == 0) return;
    hanoi(n - 1, from, via, to);
    moves++;
    if (n >= 3)
        printf("move disk %d: %c -> %c\n", n, from, to);
    hanoi(n - 1, via, to, from);
}

int main() {
    hanoi(5, 'A', 'C', 'B');
    printf("total moves: %d (2^5 - 1 = %d)\n", moves, (1 << 5) - 1);
    return 0;
}
