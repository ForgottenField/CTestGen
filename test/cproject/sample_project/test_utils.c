#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "utils.h"

int main(void) {
    int result;
    int out_value;
    
    result = parse_positive_int(NULL, &out_value);
    printf("NULL s -> %d (expected -1)\n", result);
    
    result = parse_positive_int("123", NULL);
    printf("NULL out_value -> %d (expected -1)\n", result);
    
    result = parse_positive_int("", &out_value);
    printf("empty string -> %d (expected -1)\n", result);
    
    result = parse_positive_int("0", &out_value);
    printf("'0' -> %d, out_value=%d (expected 0, 0)\n", result, out_value);
    
    result = parse_positive_int("123", &out_value);
    printf("'123' -> %d, out_value=%d (expected 0, 123)\n", result, out_value);
    
    result = parse_positive_int("12a", &out_value);
    printf("'12a' -> %d (expected -2)\n", result);
    
    result = parse_positive_int("a123", &out_value);
    printf("'a123' -> %d (expected -2)\n", result);
    
    result = parse_positive_int("1000001", &out_value);
    printf("'1000001' -> %d (expected -3)\n", result);
    
    result = parse_positive_int("1000000", &out_value);
    printf("'1000000' -> %d, out_value=%d (expected 0, 1000000)\n", result, out_value);
    
    result = parse_positive_int("999999", &out_value);
    printf("'999999' -> %d, out_value=%d (expected 0, 999999)\n", result, out_value);
    
    result = parse_positive_int("1000000", &out_value);
    printf("'1000000' -> %d, out_value=%d (expected 0, 1000000)\n", result, out_value);
    
    printf("\nAll tests completed.\n");
    return 0;
}