#ifndef UTILS_H
#define UTILS_H

#include <stddef.h>

int clamp_int(int value, int low, int high);
int ascii_sum(const char *s);
int parse_positive_int(const char *s, int *out_value);
int split_kv(const char *input, char *key, size_t key_cap, char *value, size_t value_cap);

#endif

