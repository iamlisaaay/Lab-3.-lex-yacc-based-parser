/* Двовимірні масиви: множення матриць, слід матриці */
#include <stdio.h>
#define N 3

int A[N][N] = {{1, 2, 3}, {4, 5, 6}, {7, 8, 9}};
int B[N][N] = {{9, 8, 7}, {6, 5, 4}, {3, 2, 1}};
int C[N][N];

void multiply() {
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            C[i][j] = 0;
            for (int k = 0; k < N; k++)
                C[i][j] += A[i][k] * B[k][j];
        }
}

void print(int m[N][N]) {
    for (int i = 0; i < N; i++) {
        for (int j = 0; j < N; j++)
            printf("%5d", m[i][j]);
        printf("\n");
    }
}

int main() {
    multiply();
    printf("A * B =\n");
    print(C);
    int trace = 0;
    for (int i = 0; i < N; i++) trace += C[i][i];
    printf("trace = %d\n", trace);
    return 0;
}
