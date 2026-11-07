/* Сортування бульбашкою та бінарний пошук: функції з параметрами-масивами */
#include <stdio.h>

void print_array(int a[], int n) {
    for (int i = 0; i < n; i++)
        printf("%d%s", a[i], i < n - 1 ? ", " : "\n");
}

void bubble_sort(int a[], int n) {
    int swapped;
    do {
        swapped = 0;
        for (int i = 1; i < n; i++) {
            if (a[i - 1] > a[i]) {
                int tmp = a[i - 1];
                a[i - 1] = a[i];
                a[i] = tmp;
                swapped = 1;
            }
        }
        n--;
    } while (swapped);
}

int binary_search(int a[], int n, int key) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (a[mid] == key) return mid;
        else if (a[mid] < key) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}

int main() {
    int data[] = {64, 34, 25, 12, 22, 11, 90, 5, -3, 42};
    int n = sizeof(data) / sizeof(data[0]);
    printf("Before: ");
    print_array(data, n);
    bubble_sort(data, n);
    printf("After:  ");
    print_array(data, n);
    printf("index of 22 = %d, index of 7 = %d\n", binary_search(data, n, 22), binary_search(data, n, 7));
    return 0;
}
