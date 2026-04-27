#ifndef THIRD_PARTY_ADAPTER_H
#define THIRD_PARTY_ADAPTER_H

#include <stddef.h>
#include <stdint.h>

int tp_rle_decompress(
    const uint8_t *compressed,
    size_t compressed_len,
    uint8_t *out,
    size_t out_cap,
    size_t *out_len
);

#endif

