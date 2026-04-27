#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include <ctype.h>

#include "/home/yanghq/csa-testgen/stubs/lib_stubs.h"

#include "/home/yanghq/csa-testgen/test/cproject/sample_project/src/utils.c"

static void driver_clamp_int(void) {
    int value;
    int low;
    int high;
    scanf("%d %d %d", &value, &low, &high);
    int _r = clamp_int(value, low, high);
    (void)_r;
}

static void driver_ascii_sum(void) {
    char s_buf[256] = {0};
    scanf("%255s", s_buf);
    char *s = (char *)malloc(strlen(s_buf) + 1);
    if (s) strcpy(s, s_buf);
    int _r = ascii_sum(s);
    (void)_r;
    free(s);
}

static void driver_parse_positive_int(void) {
    char s_buf[256] = {0};
    int out_value_val;
    scanf("%255s %d", s_buf, &out_value_val);
    char *s = (char *)malloc(strlen(s_buf) + 1);
    if (s) strcpy(s, s_buf);
    int *out_value = (int *)malloc(sizeof(int));
    if (out_value) *out_value = out_value_val;
    int _r = parse_positive_int(s, out_value);
    (void)_r;
    free(s);
    free(out_value);
}

static void driver_split_kv(void) {
    char input_buf[256] = {0};
    char key_buf[256] = {0};
    size_t key_cap;
    char value_buf[256] = {0};
    size_t value_cap;
    scanf("%255s %255s %zu %255s %zu", input_buf, key_buf, &key_cap, value_buf, &value_cap);
    char *input = (char *)malloc(strlen(input_buf) + 1);
    if (input) strcpy(input, input_buf);
    char *key = (char *)malloc(strlen(key_buf) + 1);
    if (key) strcpy(key, key_buf);
    char *value = (char *)malloc(strlen(value_buf) + 1);
    if (value) strcpy(value, value_buf);
    int _r = split_kv(input, key, key_cap, value, value_cap);
    (void)_r;
    free(input);
    free(key);
    free(value);
}

int main(void) {
    driver_clamp_int();
    driver_ascii_sum();
    driver_parse_positive_int();
    driver_split_kv();
    return 0;
}
