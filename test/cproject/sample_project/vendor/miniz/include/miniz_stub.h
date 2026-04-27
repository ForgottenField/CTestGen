#ifndef MINIZ_STUB_H
#define MINIZ_STUB_H

#include <stddef.h>
#include <stdint.h>

#define MZ_STUB_OK 0
#define MZ_STUB_BAD_INPUT -1
#define MZ_STUB_NO_SPACE -2

int mz_stub_rle_decompress(
    const uint8_t *compressed,
    size_t compressed_len,
    uint8_t *out,
    size_t out_cap,
    size_t *out_len
);

#endif

