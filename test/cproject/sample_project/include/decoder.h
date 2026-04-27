#ifndef DECODER_H
#define DECODER_H

#include <stddef.h>
#include <stdint.h>

int decode_rle_frame(
    const uint8_t *compressed,
    size_t compressed_len,
    char *decoded_text,
    size_t decoded_cap,
    size_t *decoded_len
);

#endif

