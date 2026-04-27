/* KLEE harness — auto-generated from utils.c */
#include "/home/yanghq/klee/klee/include/klee/klee.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>

/* Project headers */
#include "/home/yanghq/csa-testgen/test/cproject/sample_project/include/utils.h"

static void klee_test_clamp_int(void) {
    int value;
    klee_make_symbolic(&value, sizeof(value), "value");
    int low;
    klee_make_symbolic(&low, sizeof(low), "low");
    int high;
    klee_make_symbolic(&high, sizeof(high), "high");
    int _r = clamp_int(value, low, high);
    (void)_r;
}

static void klee_test_ascii_sum(void) {
    char _buf_s[64];
    klee_make_symbolic(_buf_s, sizeof(_buf_s), "s");
    klee_assume(_buf_s[63] == '\0');
    const char *s = _buf_s;
    int _r = ascii_sum(s);
    (void)_r;
}

static void klee_test_parse_positive_int(void) {
    char _buf_s[64];
    klee_make_symbolic(_buf_s, sizeof(_buf_s), "s");
    klee_assume(_buf_s[63] == '\0');
    const char *s = _buf_s;
    int _local_out_value = 0;
    int* out_value = &_local_out_value;
    int _r = parse_positive_int(s, out_value);
    (void)_r;
}

static void klee_test_split_kv(void) {
    char _buf_input[64];
    klee_make_symbolic(_buf_input, sizeof(_buf_input), "input");
    klee_assume(_buf_input[63] == '\0');
    const char *input = _buf_input;
    char _buf_key[64];
    memset(_buf_key, 0, sizeof(_buf_key));
    char *key = _buf_key;
    size_t key_cap;
    klee_make_symbolic(&key_cap, sizeof(key_cap), "key_cap");
    char _buf_value[64];
    memset(_buf_value, 0, sizeof(_buf_value));
    char *value = _buf_value;
    size_t value_cap;
    klee_make_symbolic(&value_cap, sizeof(value_cap), "value_cap");
    int _r = split_kv(input, key, key_cap, value, value_cap);
    (void)_r;
}

int main(void) {
    unsigned klee_choice;
    klee_make_symbolic(&klee_choice, sizeof(klee_choice), "choice");
    klee_assume(klee_choice < 4u);
    switch (klee_choice) {
        case 0: klee_test_clamp_int(); break;
        case 1: klee_test_ascii_sum(); break;
        case 2: klee_test_parse_positive_int(); break;
        case 3: klee_test_split_kv(); break;
        default: break;
    }
    return 0;
}
