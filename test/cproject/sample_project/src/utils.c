#include "utils.h"

#include <ctype.h>
#include <string.h>

int clamp_int(int value, int low, int high) {
    if (low > high) {
        return value;
    }
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}

int ascii_sum(const char *s) {
    if (s == NULL) {
        return -1;
    }
    int total = 0;
    for (size_t i = 0; s[i] != '\0'; ++i) {
        total += (unsigned char)s[i];
    }
    return total;
}

int parse_positive_int(const char *s, int *out_value) {
    if (s == NULL || out_value == NULL || *s == '\0') {
        return -1;
    }
    int value = 0;
    for (size_t i = 0; s[i] != '\0'; ++i) {
        if (!isdigit((unsigned char)s[i])) {
            return -2;
        }
        value = (value * 10) + (s[i] - '0');
        if (value > 1000000) {
            return -3;
        }
    }
    *out_value = value;
    return 0;
}

int split_kv(const char *input, char *key, size_t key_cap, char *value, size_t value_cap) {
    if (input == NULL || key == NULL || value == NULL || key_cap == 0 || value_cap == 0) {
        return -1;
    }
    const char *eq = strchr(input, '=');
    if (eq == NULL || eq == input || eq[1] == '\0') {
        return -2;
    }
    size_t key_len = (size_t)(eq - input);
    size_t value_len = strlen(eq + 1);
    if (key_len + 1 > key_cap || value_len + 1 > value_cap) {
        return -3;
    }
    memcpy(key, input, key_len);
    key[key_len] = '\0';
    memcpy(value, eq + 1, value_len);
    value[value_len] = '\0';
    return 0;
}

