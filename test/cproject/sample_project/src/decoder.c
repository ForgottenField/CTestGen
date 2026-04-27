#include "decoder.h"

#include "third_party_adapter.h"

int decode_rle_frame(
    const uint8_t *compressed,
    size_t compressed_len,
    char *decoded_text,
    size_t decoded_cap,
    size_t *decoded_len
) {
    if (decoded_text == 0 || decoded_len == 0) {
        return -1;
    }
    size_t out_len = 0;
    int rc = tp_rle_decompress(
        compressed,
        compressed_len,
        (uint8_t *)decoded_text,
        decoded_cap > 0 ? decoded_cap - 1 : 0,
        &out_len
    );
    if (rc != 0) {
        return -2;
    }
    decoded_text[out_len] = '\0';
    *decoded_len = out_len;
    return 0;
}

