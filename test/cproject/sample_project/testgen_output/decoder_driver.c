#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdint.h>
#include <ctype.h>

#include "/home/yanghq/csa-testgen/stubs/lib_stubs.h"

#include "/home/yanghq/csa-testgen/test/cproject/sample_project/src/decoder.c"

static void driver_decode_rle_frame(void) {
    uint8_t *compressed = (uint8_t *)calloc(1, sizeof(uint8_t));
    size_t compressed_len;
    char decoded_text_buf[256] = {0};
    size_t decoded_cap;
    size_t decoded_len_val;
    scanf("%zu %255s %zu %zu", &compressed_len, decoded_text_buf, &decoded_cap, &decoded_len_val);
    char *decoded_text = (char *)malloc(strlen(decoded_text_buf) + 1);
    if (decoded_text) strcpy(decoded_text, decoded_text_buf);
    size_t *decoded_len = (size_t *)malloc(sizeof(size_t));
    if (decoded_len) *decoded_len = decoded_len_val;
    int _r = decode_rle_frame(compressed, compressed_len, decoded_text, decoded_cap, decoded_len);
    (void)_r;
    free(compressed);
    free(decoded_text);
    free(decoded_len);
}

int main(void) {
    driver_decode_rle_frame();
    return 0;
}
