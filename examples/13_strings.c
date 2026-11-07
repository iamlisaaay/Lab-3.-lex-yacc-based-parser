/* Рядки як масиви char: довжина, реверс, паліндроми, putchar */
#include <stdio.h>

int length(char s[]) {
    int n = 0;
    while (s[n] != '\0') n++;
    return n;
}

void reverse(char s[]) {
    int i = 0, j = length(s) - 1;
    while (i < j) {
        char t = s[i];
        s[i++] = s[j];
        s[j--] = t;
    }
}

int is_palindrome(char s[]) {
    int n = length(s);
    for (int i = 0; i < n / 2; i++)
        if (s[i] != s[n - 1 - i]) return 0;
    return 1;
}

void to_upper(char s[]) {
    for (int i = 0; s[i]; i++)
        if (s[i] >= 'a' && s[i] <= 'z')
            s[i] = s[i] - 'a' + 'A';
}

int main() {
    char word[] = "compiler";
    char pal[] = "level";
    printf("word = %s, length = %d, strlen = %d\n", word, length(word), strlen(word));
    reverse(word);
    printf("reversed = %s\n", word);
    printf("\"%s\" palindrome? %d; \"%s\" palindrome? %d\n", pal, is_palindrome(pal), word, is_palindrome(word));
    to_upper(pal);
    puts(pal);
    for (char c = 'a'; c <= 'e'; c++) putchar(c);
    putchar('\n');
    return 0;
}
